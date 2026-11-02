from pydantic import BaseModel, Field, field_validator


class VpnAccountSchema(BaseModel):
    """Учетная запись VPN пользователя."""
    login: str = Field(..., description="Логин учетной записи VPN", examples=["vpn_user"])
    password: str = Field(..., description="Пароль учетной записи VPN", examples=["SecretPass123"])
    vpn_ip: str = Field(..., description="Выделенный статический IP-адрес VPN", examples=["10.10.15.45"])
    host_ip: str | None = Field(None, description="Привязанный IP или MAC рабочего места", examples=["10.100.0.144"])


class VpnSettingsSchema(BaseModel):
    """Сетевые параметры VPN-подключения корпоративной сети."""
    vpn_server: str = Field(default="vpn.corp.local", description="DNS-имя или IP-адрес VPN-сервера")
    vpn_type: str = Field(default="PPTP", description="Тип тоннеля")
    vpn_encryption: str = Field(default="без шифрования", description="Требования к шифрованию")
    vpn_auth_method: str = Field(default="MS-CHAP v2", description="Метод проверки подлинности")
    vpn_accounts: list[VpnAccountSchema] = Field(
        default_factory=list,
        description="Список привязанных учетных записей VPN"
    )


class EmployeeInfoSchema(BaseModel):
    """Служебные и персональные данные сотрудника (пользовательские атрибуты биллинга)."""
    full_name: str = Field(..., description="Ф.И.О. сотрудника", examples=["Иванов Иван Иванович"])
    building: str = Field(default="1", description="Номер корпуса", examples=["1", "2", "8"])
    position: str = Field(..., description="Должность и подразделение", examples=["Инженер технической поддержки"])
    room: str = Field(..., description="Номер кабинета", examples=["305"])
    phone: str = Field(..., description="Внутренний номер телефона", examples=["12-34"])
    tariff: str = Field(default="Безлимитный", description="Название тарифного плана")


class NetworkInfoSchema(BaseModel):
    """Сетевые реквизиты рабочего места."""
    inventory_number: str | None = Field(None, description="Инвентарный номер ПК", examples=["01340056"])
    ip_addresses: list[str] = Field(
        default_factory=list,
        description="Список локальных IP-адресов",
        examples=[["10.100.0.144"]]
    )
    mac_addresses: list[str] = Field(
        default_factory=list,
        description="Список MAC-адресов сетевых интерфейсов"
    )

    @field_validator("mac_addresses", mode="before")
    @classmethod
    def normalize_mac_list(cls, values: list) -> list:
        """
        Приводит MAC-адрес к единому стандартному виду:
        - Перевод всех символов в верхний регистр.
        - Замена разделителей ':' на '-'.
        Пример: 00:11:22:33:44:55 -> 00-11-22-33-44-55
        """
        if not isinstance(values, list):
            return values

        normalized = []
        for mac in values:
            if isinstance(mac, str):
                cleaned = mac.strip().upper().replace(":", "-")
                normalized.append(cleaned)
            else:
                normalized.append(mac)

        return normalized


class StatAccessSchema(BaseModel):
    """Реквизиты для доступа к веб-интерфейсу статистики."""
    stat_server: str = Field(default="utmweb.corp.local", description="Адрес сервера статистики")
    stat_login: str = Field(..., description="Логин абонента", examples=["user"])
    stat_password: str = Field(..., description="Пароль абонента", examples=["UserPass123"])


class MemoResponseSchema(BaseModel):
    """Итоговая структура памятки сотрудника."""
    employee: EmployeeInfoSchema
    network: NetworkInfoSchema
    statistics: StatAccessSchema
    vpn: VpnSettingsSchema
