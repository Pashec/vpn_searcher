import asyncio
import hashlib
import io
import logging
import re
import socket
import ssl
import struct
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from app.core.certs import get_cert_paths
from app.core.config import settings
from app.schemas.memo import (
    EmployeeInfoSchema,
    MemoResponseSchema,
    NetworkInfoSchema,
    StatAccessSchema,
    UserCandidateSchema,
    UserCandidatesResponseSchema,
    VpnAccountSchema,
    VpnSettingsSchema,
)
from app.services.base import BaseMemoService

logger = logging.getLogger("utm_service")

# Константы протокола URFA
URFA_VERSION = 35

# Коды пакетов
URFA_PACKET_HANDSHAKE = 192      # 0xC0: Вызов от сервера с сессионным challenge
URFA_PACKET_ACCESS_REQUEST = 193 # 0xC1: Запрос авторизации клиента
URFA_PACKET_ACCESS_ACCEPT = 194  # 0xC2: Успешная авторизация
URFA_PACKET_ACCESS_REJECT = 195  # 0xC3: Отказ в авторизации
URFA_PACKET_DATA = 200           # 0xC8: Передача аргументов или результатов RPC
URFA_PACKET_INVOKE = 201         # 0xC9: Инициация вызова функции

# Типы атрибутов
URFA_ATTR_LOGIN_TYPE = 1         # 2 = LOGIN_SYSTEM
URFA_ATTR_LOGIN = 2              # Строка логина
URFA_ATTR_INVOKE = 3             # 4-байтный идентификатор вызываемой функции (RPC FID)
URFA_ATTR_TERMINATION = 4        # Признак завершения потока данных
URFA_ATTR_DATA = 5               # Полезная нагрузка (аргументы и результаты)
URFA_ATTR_CHALLENGE = 8          # Случайная 16-байтовая последовательность от сервера
URFA_ATTR_RESPONSE = 9           # MD5(challenge + password)
URFA_ATTR_SSL_REQUEST = 10       # 5 = SSL_TLS1_CERT (NetUP TLS с сертификатом)

# Идентификаторы функций RPC ядра биллинга
RPC_SEARCH_USERS_NEW = 0x1206    # Поиск пользователей по расширенным критериям
RPC_GET_USERINFO = 0x2006        # Карточка абонента (учетные данные, ФИО, телефон, адрес)
RPC_GET_DOCUMENT = 0x4620        # Генерация печатной формы документа абонента (ODT / Памятка)

# Идентификаторы полей поиска (what_id) для rpcf_search_users_new
WHAT_ID_USER_ID = 1
WHAT_ID_LOGIN = 2
WHAT_ID_FULL_NAME = 5
WHAT_ID_WORK_PHONE = 13          # Рабочий телефон абонента
WHAT_ID_HOME_PHONE = 14          # Содержит MAC-адрес рабочего места
WHAT_ID_ROOM = 22                # Номер кабинета / аудитории (flat_number)
WHAT_ID_FLOOR = 24               # Содержит локальный IP-адрес рабочего места
WHAT_ID_IP = 28                  # IP-адрес из связки услуг (VPN / IP-трафик)
WHAT_ID_BUILDING = 41            # Номер корпуса
WHAT_ID_MAC = 42                 # MAC-адрес из связки услуг

# Критерии сравнения (criteria_id)
CRITERIA_LIKE = 1
CRITERIA_EQ = 3

# Стандартные коды колонок для запроса в rpcf_search_users_new
POLE_WORK_TEL = 13
POLE_ROOM = 22
POLE_FLOOR_IP = 24
POLE_BUILDING = 41
DEFAULT_SEARCH_POLES = [POLE_WORK_TEL, POLE_ROOM, POLE_FLOOR_IP, POLE_BUILDING]


def _build_packet(code: int, version: int, attributes: list[bytes]) -> bytes:
    """Формирует пакет URFA: 4 байта заголовка (>BBH: код, версия, длина) + атрибуты."""
    body = b"".join(attributes)
    length = 4 + len(body)
    header = struct.pack(">BBH", code, version, length)
    return header + body


def _build_attr(attr_type: int, data: bytes) -> bytes:
    """Формирует TLV-атрибут: 4 байта заголовка (>BBH: тип, 0, длина) + данные."""
    length = 4 + len(data)
    header = struct.pack(">BBH", attr_type, 0, length)
    return header + data


def _build_attr_int(attr_type: int, val: int) -> bytes:
    """Формирует TLV-атрибут с 4-байтным целым числом."""
    return _build_attr(attr_type, struct.pack(">i", val))


def _build_attr_str(attr_type: int, text: str) -> bytes:
    """Формирует TLV-атрибут с UTF-8 строкой."""
    return _build_attr(attr_type, text.encode("utf-8"))


def _read_packet(sock: socket.socket) -> tuple[tuple[int, int, int] | None, list[tuple[int, bytes]]]:
    """
    Считывает полный пакет URFA из сокета:
    сначала 4-байтный заголовок, затем тело пакета, и десериализует список атрибутов.
    """
    hdr_bytes = sock.recv(4)
    if not hdr_bytes or len(hdr_bytes) < 4:
        return None, []

    code, version, length = struct.unpack(">BBH", hdr_bytes)
    remaining = length - 4
    body = bytearray()
    while len(body) < remaining:
        chunk = sock.recv(remaining - len(body))
        if not chunk:
            break
        body.extend(chunk)

    data = hdr_bytes + body
    attributes: list[tuple[int, bytes]] = []
    idx = 4
    while idx < length and idx < len(data):
        if idx + 4 > len(data):
            break
        atype, _, alen = struct.unpack(">BBH", data[idx:idx + 4])
        adata = bytes(data[idx + 4:idx + alen])
        attributes.append((atype, adata))
        idx += alen

    return (code, version, length), attributes


def _parse_ip_bytes(raw: bytes) -> str | None:
    """Десериализует IP-адрес из бинарного формата (4, 5 или 8 байт)."""
    if len(raw) == 4:
        return socket.inet_ntoa(raw)
    if len(raw) == 5 and raw[0] == 4:
        return socket.inet_ntoa(raw[1:5])
    if len(raw) == 8 and raw[0] == 7:
        return socket.inet_ntoa(raw[4:8])
    return None


def _clean_str(val: str) -> str:
    """Очищает строку от мусора и начальных спецсимволов."""
    return val.strip(" !\t\r\n")


def _parse_odt_document(doc_bytes: bytes) -> dict[str, str]:
    """
    Парсит бинарный архив памятки формата OpenDocument Text (.odt),
    извлекает значения служебных переменных из content.xml.
    """
    fields: dict[str, str] = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(doc_bytes))
        content_xml = zf.read("content.xml")
        root = ET.fromstring(content_xml)
        for el in root.iter():
            if el.tag.endswith("user-field-decl"):
                name = None
                val = None
                for k, v in el.attrib.items():
                    if k.endswith("name"):
                        name = v
                    elif k.endswith("string-value") or k.endswith("value"):
                        val = v
                if name and val is not None:
                    fields[name] = val
    except Exception as e:
        logger.warning(f"Не удалось распарсить ODT документ памятки: {e}")
    return fields


class UrfaConnection:
    """Низкоуровневый клиент протокола NetUP URFA поверх защищенного TLS-соединения."""

    def __init__(self, host: str, port: int, login: str, password: str, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.login = login
        self.password = password
        self.timeout = timeout
        self.sock: ssl.SSLSocket | None = None

    def connect(self) -> None:
        """
        Выполняет TCP-подключение, рукопожатие URFA Handshake,
        CHAP MD5 аутентификацию и оборачивание соединения в TLS с клиентским сертификатом.
        """
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(self.timeout)
        raw_sock.connect((self.host, self.port))

        try:
            # 1. Получение сессионного challenge (пакет 192)
            hdr, attrs = _read_packet(raw_sock)
            if not hdr or hdr[0] != URFA_PACKET_HANDSHAKE or not attrs:
                raise ConnectionError("Сервер биллинга не вернул сессионный challenge (пакет 192)")

            challenge = attrs[0][1]

            # 2. Вычисление CHAP MD5 ответа: MD5(challenge + password)
            md5 = hashlib.md5()
            md5.update(challenge)
            md5.update(self.password.encode("utf-8"))
            chap_response = md5.digest()

            # 3. Отправка Access Request (пакет 193)
            auth_attrs = [
                _build_attr(URFA_ATTR_LOGIN, self.login.encode("utf-8")),
                _build_attr(URFA_ATTR_RESPONSE, chap_response),
                _build_attr(URFA_ATTR_CHALLENGE, challenge),
                _build_attr_int(URFA_ATTR_LOGIN_TYPE, 2),    # LOGIN_SYSTEM
                _build_attr_int(URFA_ATTR_SSL_REQUEST, 5),   # SSL_TLS1_CERT
            ]
            raw_sock.sendall(_build_packet(URFA_PACKET_ACCESS_REQUEST, URFA_VERSION, auth_attrs))

            # 4. Проверка Access Accept (пакет 194)
            rhdr, _ = _read_packet(raw_sock)
            if not rhdr or rhdr[0] != URFA_PACKET_ACCESS_ACCEPT:
                code_desc = f"код {rhdr[0]}" if rhdr else "соединение закрыто"
                raise PermissionError(f"Авторизация в биллинге отклонена ({code_desc})")

            # 5. Оборачивание соединения в TLS с клиентским сертификатом
            cert_file, key_file = get_cert_paths()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")

            self.sock = ctx.wrap_socket(raw_sock)
        except Exception:
            raw_sock.close()
            raise

    def close(self) -> None:
        """Корректно закрывает защищенное соединение."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def call_rpc(self, func_id: int, args_attrs: list[bytes]) -> list[bytes]:
        """
        Вызывает RPC-функцию по ее ID, передает аргументы
        и вычитывает все возвращенные атрибуты типа DATA (5) до признака завершения (4).
        """
        if not self.sock:
            raise ConnectionError("Соединение с сервером биллинга не установлено")

        # Отправляем пакет вызова функции (пакет 201)
        self.sock.sendall(_build_packet(URFA_PACKET_INVOKE, URFA_VERSION, [_build_attr_int(URFA_ATTR_INVOKE, func_id)]))

        # Вычитываем подтверждение (Ack 200)
        ack_hdr, ack_attrs = _read_packet(self.sock)
        if not ack_hdr or ack_hdr[0] != URFA_PACKET_DATA:
            raise RuntimeError(f"Сервер не подтвердил вызов RPC 0x{func_id:04x}")

        has_invoke = any(t == URFA_ATTR_INVOKE for t, _ in ack_attrs)
        if not has_invoke:
            raise PermissionError(f"Вызов RPC 0x{func_id:04x} отклонен сервером (недостаточно прав)")

        # Передаем атрибуты аргументов (пакет 200)
        self.sock.sendall(_build_packet(URFA_PACKET_DATA, URFA_VERSION, args_attrs))

        # Считываем пакеты ответа до атрибута завершения (4)
        result_data: list[bytes] = []
        while True:
            res_hdr, res_attrs = _read_packet(self.sock)
            if not res_hdr:
                break
            has_term = any(t == URFA_ATTR_TERMINATION for t, _ in res_attrs)
            for t, data in res_attrs:
                if t == URFA_ATTR_DATA:
                    result_data.append(data)
            if has_term:
                break

        return result_data

    def search_users_new(
        self,
        what_id: int,
        criteria_id: int,
        pattern: str,
        poles: list[int] | None = None
    ) -> list[bytes]:
        """Вызывает RPC rpcf_search_users_new (0x1206) с заданным критерием и списком полей."""
        if poles is None:
            poles = DEFAULT_SEARCH_POLES

        args = [_build_attr_int(URFA_ATTR_DATA, len(poles))]
        for p in poles:
            args.append(_build_attr_int(URFA_ATTR_DATA, p))

        args.extend([
            _build_attr_int(URFA_ATTR_DATA, 0),             # inSelectType = 0
            _build_attr_int(URFA_ATTR_DATA, 1),             # inPatternsCount = 1
            _build_attr_int(URFA_ATTR_DATA, what_id),       # inWhatId
            _build_attr_int(URFA_ATTR_DATA, criteria_id),   # inCriteriaId
            _build_attr_str(URFA_ATTR_DATA, pattern),       # inPattern
        ])
        return self.call_rpc(RPC_SEARCH_USERS_NEW, args)

    def get_userinfo(self, user_id: int) -> list[bytes]:
        """Вызывает RPC rpcf_get_userinfo (0x2006) для получения детальной карточки абонента."""
        args = [
            _build_attr_int(URFA_ATTR_DATA, user_id),
        ]
        return self.call_rpc(RPC_GET_USERINFO, args)

    def get_user_document(
        self,
        user_id: int,
        doc_type: int = 3,
        file_type: int = 1
    ) -> bytes | None:
        """
        Вызывает RPC rpcf_get_document (0x4620) для формирования документа памятки (ODT).
        Возвращает полные байты архива ODT или None в случае ошибки.
        """
        args = [
            _build_attr_int(URFA_ATTR_DATA, user_id),
            _build_attr_int(URFA_ATTR_DATA, doc_type),       # 3 = Памятка пользователя
            _build_attr_int(URFA_ATTR_DATA, user_id),       # base_id = user_id
            _build_attr_int(URFA_ATTR_DATA, file_type),     # 1 = .odt
        ]
        try:
            res = self.call_rpc(RPC_GET_DOCUMENT, args)
            if not res or len(res) < 3:
                return None
            res_code = struct.unpack(">i", res[0])[0]
            if res_code != 0:
                logger.warning(f"RPC 0x4620 вернул код ошибки {res_code} для user_id={user_id}")
                return None
            # res[1] — количество чанков, res[2:] — бинарные чанки документа
            return b"".join(res[2:])
        except Exception as e:
            logger.warning(f"Ошибка при вызове rpcf_get_document для user_id={user_id}: {e}")
            return None


class UrfaMemoService(BaseMemoService):
    """
    Клиент для взаимодействия с ядром биллинга по сетевому протоколу URFA (TCP 11758).
    Выполняет защищенное TLS-подключение, поиск абонентов, выгрузку официальной памятки
    и учетных записей VPN с паролями.
    """

    def __init__(self):
        self.host = settings.UTM_HOST
        self.port = settings.UTM_PORT
        self.login = settings.UTM_LOGIN
        self.password = settings.UTM_PASSWORD
        self.timeout = 5.0

    def _parse_candidates_from_search(self, raw_data: list[bytes]) -> list[UserCandidateSchema]:
        """Парсит список найденных абонентов из ответа rpcf_search_users_new с доп. полями."""
        if not raw_data:
            return []

        user_count = struct.unpack(">i", raw_data[0])[0]
        candidates: list[UserCandidateSchema] = []
        idx = 1

        for _ in range(user_count):
            if idx >= len(raw_data):
                break
            uid = struct.unpack(">i", raw_data[idx])[0]; idx += 1
            login = raw_data[idx].decode("utf-8", errors="replace"); idx += 1
            basic_account = struct.unpack(">i", raw_data[idx])[0]; idx += 1
            full_name = _clean_str(raw_data[idx].decode("utf-8", errors="replace")); idx += 1
            is_blocked = struct.unpack(">i", raw_data[idx])[0]; idx += 1
            balance = struct.unpack(">d", raw_data[idx])[0]; idx += 1

            ip_addr_size = struct.unpack(">i", raw_data[idx])[0]; idx += 1
            assigned_ips: list[str] = []
            for _ in range(ip_addr_size):
                if idx >= len(raw_data):
                    break
                group_size = struct.unpack(">i", raw_data[idx])[0]; idx += 1
                for _ in range(group_size):
                    if idx + 2 >= len(raw_data):
                        break
                    _ = struct.unpack(">i", raw_data[idx])[0]; idx += 1
                    raw_ip = raw_data[idx]; idx += 1
                    _ = raw_data[idx]; idx += 1
                    parsed_ip = _parse_ip_bytes(raw_ip)
                    if parsed_ip and parsed_ip not in assigned_ips:
                        assigned_ips.append(parsed_ip)

            # Чтение запрошенных колонок: [POLE_WORK_TEL, POLE_ROOM, POLE_FLOOR_IP, POLE_BUILDING]
            work_tel = raw_data[idx].decode("utf-8", errors="replace").strip() if idx < len(raw_data) else ""; idx += 1
            room = raw_data[idx].decode("utf-8", errors="replace").strip() if idx < len(raw_data) else ""; idx += 1
            floor_ip = raw_data[idx].decode("utf-8", errors="replace").strip() if idx < len(raw_data) else ""; idx += 1
            building = raw_data[idx].decode("utf-8", errors="replace").strip() if idx < len(raw_data) else ""; idx += 1

            display_ip = floor_ip if floor_ip else (assigned_ips[0] if assigned_ips else None)

            candidates.append(
                UserCandidateSchema(
                    user_id=uid,
                    full_name=full_name or "Не указано",
                    login=login,
                    building=building or None,
                    room=room or None,
                    phone=work_tel or None,
                    ip=display_ip or None,
                )
            )

        return candidates

    def _build_memo_response(self, conn: UrfaConnection, user_id: int) -> MemoResponseSchema | None:
        """
        Формирует полную карточку памятки абонента:
        1. Считывает официальный документ памятки (RPC 0x4620), откуда извлекает
           точные логины, пароли и IP-адреса всех учетных записей VPN, а также пароль ЛК статистики.
        2. Считывает детальные атрибуты абонента (RPC 0x2006) для получения должности,
           подразделения, номера комнаты, телефона, тарифа и MAC-адреса.
        """
        # 1. Извлечение данных из карточки пользователя (0x2006)
        uinfo = conn.get_userinfo(user_id)
        if not uinfo or len(uinfo) < 8:
            logger.warning(f"Не удалось получить данные абонента ID={user_id} через get_userinfo")
            return None

        accounts_count = struct.unpack(">i", uinfo[1])[0]
        pos = 2 + accounts_count * 2

        u_login = uinfo[pos].decode("utf-8", errors="replace")
        u_password = uinfo[pos + 1].decode("utf-8", errors="replace")
        u_full_name = _clean_str(uinfo[pos + 3].decode("utf-8", errors="replace"))

        u_work_tel = uinfo[pos + 11].decode("utf-8", errors="replace").strip()
        u_home_tel = uinfo[pos + 12].decode("utf-8", errors="replace").strip()
        u_position = uinfo[pos + 15].decode("utf-8", errors="replace").strip()
        u_room = uinfo[pos + 27].decode("utf-8", errors="replace").strip()
        u_floor = uinfo[pos + 29].decode("utf-8", errors="replace").strip()
        u_tariff = uinfo[pos + 30].decode("utf-8", errors="replace").strip()
        u_building = uinfo[pos + 31].decode("utf-8", errors="replace").strip()

        # 2. Выгрузка официальной памятки через RPC 0x4620 (ODT документ)
        doc_bytes = conn.get_user_document(user_id=user_id, doc_type=3, file_type=1)
        doc_fields: dict[str, str] = {}
        if doc_bytes:
            doc_fields = _parse_odt_document(doc_bytes)

        # 3. Извлечение учетных записей VPN
        vpn_accounts: list[VpnAccountSchema] = []
        if doc_fields:
            i = 0
            while True:
                k_login = f"ipgroup.login{i}"
                if k_login not in doc_fields:
                    break
                acc_login = doc_fields.get(k_login, "").strip()
                acc_pass = doc_fields.get(f"ipgroup.password{i}", "").strip()
                acc_ip = doc_fields.get(f"ipgroup.ip{i}", "").strip()
                acc_host = doc_fields.get(f"ipgroup.mac{i}") or doc_fields.get(f"ipgroup.cid{i}") or None
                if acc_host:
                    acc_host = acc_host.strip()
                    if not acc_host or acc_host.startswith("<"):
                        acc_host = None

                if acc_login or acc_ip:
                    vpn_accounts.append(
                        VpnAccountSchema(
                            login=acc_login,
                            password=acc_pass,
                            vpn_ip=acc_ip,
                            host_ip=acc_host,
                        )
                    )
                i += 1

        # Запасной вариант, если памятка не сгенерировалась
        if not vpn_accounts and u_login:
            vpn_accounts.append(
                VpnAccountSchema(
                    login=u_login,
                    password=u_password,
                    vpn_ip="",
                    host_ip=u_floor if u_floor else None,
                )
            )

        # 4. Логин и пароль ЛК статистики (из документа памятки либо из карточки)
        stat_login = doc_fields.get("user.login") or u_login
        stat_password = doc_fields.get("user.password") or u_password

        # 5. Сетевые адреса
        ip_addresses: list[str] = []
        if u_floor:
            ip_addresses.append(u_floor)
        for acc in vpn_accounts:
            if acc.vpn_ip and acc.vpn_ip not in ip_addresses:
                ip_addresses.append(acc.vpn_ip)

        mac_addresses: list[str] = []
        if u_home_tel:
            mac_addresses.append(u_home_tel)

        # 6. Служебная информация сотрудника
        employee = EmployeeInfoSchema(
            full_name=u_full_name or doc_fields.get("user.full_name") or "Не указано",
            position=u_position or doc_fields.get("user.icq_number") or "Сотрудник",
            building=u_building or doc_fields.get("user.building") or "1",
            room=u_room or doc_fields.get("user.flat_number") or "-",
            phone=u_work_tel or doc_fields.get("user.work_telephone") or "-",
            tariff=u_tariff or doc_fields.get("user.district") or "Безлимитный",
        )

        network = NetworkInfoSchema(
            inventory_number=None,
            ip_addresses=ip_addresses,
            mac_addresses=mac_addresses,
        )

        statistics = StatAccessSchema(
            stat_server=settings.STAT_SERVER,
            stat_login=stat_login,
            stat_password=stat_password,
        )

        vpn = VpnSettingsSchema(
            vpn_server=settings.VPN_SERVER,
            vpn_type="PPTP",
            vpn_encryption="без шифрования",
            vpn_auth_method="MS-CHAP v2",
            vpn_accounts=vpn_accounts,
        )

        return MemoResponseSchema(
            employee=employee,
            network=network,
            statistics=statistics,
            vpn=vpn,
        )

    def _sync_search(
        self,
        search_type: str,
        query_value: str
    ) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """
        Синхронный поиск пользователей в ядре биллинга:
        - Если найдено 0 пользователей: возвращает None.
        - Если найден ровно 1 пользователь: сразу формирует и возвращает готовую памятку.
        - Если найдено несколько совпадений: возвращает список кандидатов для выбора.
        """
        conn = UrfaConnection(
            host=self.host,
            port=self.port,
            login=self.login,
            password=self.password,
            timeout=self.timeout,
        )

        try:
            conn.connect()
            logger.info(f"Подключение к биллингу установлено: поиск {search_type}='{query_value}'")

            candidates: list[UserCandidateSchema] = []

            # --- 1. Поиск по Ф.И.О. или логину ---
            if search_type == "name":
                res = conn.search_users_new(WHAT_ID_FULL_NAME, CRITERIA_LIKE, query_value)
                candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_LOGIN, CRITERIA_EQ, query_value)
                    candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_LOGIN, CRITERIA_LIKE, query_value)
                    candidates = self._parse_candidates_from_search(res)

            # --- 2. Поиск по IP-адресу ---
            elif search_type == "ip":
                # Сначала ищем по IP-адресу из связки услуг
                res = conn.search_users_new(WHAT_ID_IP, CRITERIA_EQ, query_value)
                candidates = self._parse_candidates_from_search(res)

                # Затем по локальному IP рабочего места (floor)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_FLOOR, CRITERIA_EQ, query_value)
                    candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_FLOOR, CRITERIA_LIKE, query_value)
                    candidates = self._parse_candidates_from_search(res)

            # --- 3. Поиск по MAC-адресу ---
            elif search_type == "mac":
                clean_mac = re.sub(r"[^0-9A-Fa-f]", "", query_value).upper()
                mac_hyphen = "-".join(clean_mac[i:i + 2] for i in range(0, len(clean_mac), 2))
                mac_colon = ":".join(clean_mac[i:i + 2] for i in range(0, len(clean_mac), 2))

                # Поиск по MAC в поле контактного телефона
                res = conn.search_users_new(WHAT_ID_HOME_PHONE, CRITERIA_LIKE, mac_hyphen)
                candidates = self._parse_candidates_from_search(res)

                if not candidates and mac_colon != mac_hyphen:
                    res = conn.search_users_new(WHAT_ID_HOME_PHONE, CRITERIA_LIKE, mac_colon)
                    candidates = self._parse_candidates_from_search(res)

                # Поиск по MAC связки услуг
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_MAC, CRITERIA_EQ, mac_colon)
                    candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_MAC, CRITERIA_EQ, mac_hyphen)
                    candidates = self._parse_candidates_from_search(res)

            if not candidates:
                logger.info(f"Абонент по критерию {search_type}='{query_value}' не найден")
                return None

            # Если найдено несколько совпадений — отдаем список кандидатов для выбора
            if len(candidates) > 1:
                logger.info(f"Найдено {len(candidates)} кандидатов по запросу '{query_value}'")
                return UserCandidatesResponseSchema(candidates=candidates)

            # Если кандидат один — сразу загружаем и отдаем полную памятку
            single_user_id = candidates[0].user_id
            logger.info(f"Найден единственный абонент ID={single_user_id}, загрузка памятки...")
            return self._build_memo_response(conn, single_user_id)

        finally:
            conn.close()

    def _sync_unified_search(
        self,
        query: str
    ) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """
        Синхронный универсальный поиск в ядре биллинга:
        - Аудитория с корпусом ('1-709', '2-709'): поиск по кабинету и фильтрация по корпусу.
        - IP-адрес ('10.100.0.144'): поиск по связкам услуг и локальному IP.
        - MAC-адрес ('77-D0', 'FF-4C', 'CD:12'): поиск в контактном телефоне и связках услуг.
        - Ф.И.О., логин абонента, номер аудитории или рабочий телефон.
        """
        q = query.strip()
        if not q:
            return None

        conn = UrfaConnection(
            host=self.host,
            port=self.port,
            login=self.login,
            password=self.password,
            timeout=self.timeout,
        )

        try:
            conn.connect()
            logger.info(f"Подключение к биллингу установлено: единый поиск query='{q}'")

            candidates: list[UserCandidateSchema] = []

            # 1. Поиск по формату аудитории с корпусом ('1-709', '2-709', '9-444')
            room_match = re.match(r"^(\d+)\s*[-/\\#\s]\s*([a-zA-Zа-яА-Я0-9]+)$", q)
            if room_match:
                building_str = room_match.group(1).strip()
                room_str = room_match.group(2).strip()

                # Ищем по номеру кабинета (WHAT_ID_ROOM)
                res = conn.search_users_new(WHAT_ID_ROOM, CRITERIA_EQ, room_str)
                found = self._parse_candidates_from_search(res)
                if not found:
                    res = conn.search_users_new(WHAT_ID_ROOM, CRITERIA_LIKE, room_str)
                    found = self._parse_candidates_from_search(res)

                # Фильтруем по номеру корпуса
                filtered = [
                    c for c in found
                    if c.building and (c.building.strip() == building_str or c.building.strip().startswith(building_str))
                ]

                # Запасной вариант: если аудитория сохранена единой строкой (например '1-709')
                if not filtered:
                    res_combo = conn.search_users_new(WHAT_ID_ROOM, CRITERIA_LIKE, f"{building_str}-{room_str}")
                    filtered = self._parse_candidates_from_search(res_combo)

                candidates = filtered

            # 2. Поиск по IP-адресу
            elif re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", q):
                res = conn.search_users_new(WHAT_ID_IP, CRITERIA_EQ, q)
                candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_FLOOR, CRITERIA_EQ, q)
                    candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_FLOOR, CRITERIA_LIKE, q)
                    candidates = self._parse_candidates_from_search(res)

            # 3. Поиск по MAC-адресу или суффиксу/фрагменту MAC (например '77-D0', 'FF-4C')
            elif bool(re.search(r"[-:]", q)) or (len(re.sub(r"[^0-9A-Za-z]", "", q)) >= 4 and all(c in "0123456789ABCDEFabcdef" for c in re.sub(r"[^0-9A-Za-z]", "", q)) and not q.isdigit()):
                clean_mac = re.sub(r"[^0-9A-Za-z]", "", q).upper()
                mac_hyphen = "-".join(clean_mac[i:i + 2] for i in range(0, len(clean_mac), 2))
                mac_colon = ":".join(clean_mac[i:i + 2] for i in range(0, len(clean_mac), 2))

                # Поиск в поле контактного телефона
                res = conn.search_users_new(WHAT_ID_HOME_PHONE, CRITERIA_LIKE, mac_hyphen)
                candidates = self._parse_candidates_from_search(res)
                if not candidates and mac_colon != mac_hyphen:
                    res = conn.search_users_new(WHAT_ID_HOME_PHONE, CRITERIA_LIKE, mac_colon)
                    candidates = self._parse_candidates_from_search(res)
                if not candidates:
                    res = conn.search_users_new(WHAT_ID_HOME_PHONE, CRITERIA_LIKE, q)
                    candidates = self._parse_candidates_from_search(res)

                # Поиск в поле связок услуг MAC
                if not candidates and len(clean_mac) >= 4:
                    res = conn.search_users_new(WHAT_ID_MAC, CRITERIA_LIKE, mac_colon)
                    candidates = self._parse_candidates_from_search(res)
                if not candidates and len(clean_mac) >= 4:
                    res = conn.search_users_new(WHAT_ID_MAC, CRITERIA_LIKE, mac_hyphen)
                    candidates = self._parse_candidates_from_search(res)

            # 4. Поиск по Ф.И.О., логину абонента или номеру кабинета/телефона
            else:
                # 4.1. Поиск по Ф.И.О.
                res = conn.search_users_new(WHAT_ID_FULL_NAME, CRITERIA_LIKE, q)
                candidates.extend(self._parse_candidates_from_search(res))

                # 4.2. Поиск по логину абонента
                if not candidates or (" " not in q and len(q) <= 30):
                    res = conn.search_users_new(WHAT_ID_LOGIN, CRITERIA_EQ, q)
                    candidates.extend(self._parse_candidates_from_search(res))
                    if not candidates:
                        res = conn.search_users_new(WHAT_ID_LOGIN, CRITERIA_LIKE, q)
                        candidates.extend(self._parse_candidates_from_search(res))

                # 4.3. Поиск по номеру кабинета (если запрос числовой, например '709' или '324')
                if not candidates and re.match(r"^\d+[a-zA-Zа-яА-Я]?$", q):
                    res = conn.search_users_new(WHAT_ID_ROOM, CRITERIA_EQ, q)
                    candidates.extend(self._parse_candidates_from_search(res))
                    if not candidates:
                        res = conn.search_users_new(WHAT_ID_ROOM, CRITERIA_LIKE, q)
                        candidates.extend(self._parse_candidates_from_search(res))

                # 4.4. Поиск по рабочему телефону
                if not candidates and re.match(r"^[\d-]+$", q):
                    res = conn.search_users_new(WHAT_ID_WORK_PHONE, CRITERIA_LIKE, q)
                    candidates.extend(self._parse_candidates_from_search(res))

            # Дедупликация кандидатов по user_id
            seen_ids = set()
            unique_candidates: list[UserCandidateSchema] = []
            for c in candidates:
                if c.user_id not in seen_ids:
                    seen_ids.add(c.user_id)
                    unique_candidates.append(c)

            if not unique_candidates:
                logger.info(f"Абонент по единому запросу '{q}' не найден")
                return None

            if len(unique_candidates) > 1:
                logger.info(f"Найдено {len(unique_candidates)} кандидатов по запросу '{q}'")
                return UserCandidatesResponseSchema(candidates=unique_candidates)

            # Ровно один абонент — сразу формируем и отдаем полную памятку
            single_user_id = unique_candidates[0].user_id
            logger.info(f"Найден единственный абонент ID={single_user_id}, загрузка памятки...")
            return self._build_memo_response(conn, single_user_id)

        finally:
            conn.close()

    def _sync_get_by_id(self, user_id: int) -> MemoResponseSchema | None:
        """Синхронная загрузка памятки по известному ID пользователя."""
        conn = UrfaConnection(
            host=self.host,
            port=self.port,
            login=self.login,
            password=self.password,
            timeout=self.timeout,
        )
        try:
            conn.connect()
            return self._build_memo_response(conn, user_id)
        finally:
            conn.close()

    async def get_by_user_id(self, user_id: int) -> MemoResponseSchema | None:
        """Получение памятки конкретного абонента по user_id."""
        try:
            return await asyncio.to_thread(self._sync_get_by_id, user_id)
        except (socket.timeout, TimeoutError):
            logger.error(f"Превышен таймаут подключения к серверу биллинга ({self.host}:{self.port})")
            raise ConnectionError(f"Сервер биллинга ({self.host}:{self.port}) не отвечает (таймаут сети).")
        except (OSError, ConnectionRefusedError, PermissionError) as e:
            logger.error(f"Сетевая ошибка при взаимодействии с сервером биллинга -> {e}")
            raise ConnectionError(f"Ошибка связи с сервером биллинга: {e}")

    async def search(self, query: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Универсальный поиск памятки или списка кандидатов по единой строке запроса."""
        try:
            return await asyncio.to_thread(self._sync_unified_search, query.strip())
        except (socket.timeout, TimeoutError):
            raise ConnectionError(f"Сервер биллинга ({self.host}:{self.port}) не отвечает (таймаут сети).")
        except (OSError, ConnectionRefusedError, PermissionError) as e:
            raise ConnectionError(f"Ошибка связи с сервером биллинга: {e}")

    async def search_by_name(self, name: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск памятки или списка кандидатов по Ф.И.О."""
        try:
            return await asyncio.to_thread(self._sync_search, "name", name.strip())
        except (socket.timeout, TimeoutError):
            raise ConnectionError(f"Сервер биллинга ({self.host}:{self.port}) не отвечает (таймаут сети).")
        except (OSError, ConnectionRefusedError, PermissionError) as e:
            raise ConnectionError(f"Ошибка связи с сервером биллинга: {e}")

    async def search_by_ip(self, ip: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск памятки или списка кандидатов по IP-адресу."""
        try:
            return await asyncio.to_thread(self._sync_search, "ip", ip.strip())
        except (socket.timeout, TimeoutError):
            raise ConnectionError(f"Сервер биллинга ({self.host}:{self.port}) не отвечает (таймаут сети).")
        except (OSError, ConnectionRefusedError, PermissionError) as e:
            raise ConnectionError(f"Ошибка связи с сервером биллинга: {e}")

    async def search_by_mac(self, mac: str) -> MemoResponseSchema | UserCandidatesResponseSchema | None:
        """Поиск памятки или списка кандидатов по MAC-адресу."""
        normalized_mac = mac.strip().upper().replace(":", "-")
        try:
            return await asyncio.to_thread(self._sync_search, "mac", normalized_mac)
        except (socket.timeout, TimeoutError):
            raise ConnectionError(f"Сервер биллинга ({self.host}:{self.port}) не отвечает (таймаут сети).")
        except (OSError, ConnectionRefusedError, PermissionError) as e:
            raise ConnectionError(f"Ошибка связи с сервером биллинга: {e}")
