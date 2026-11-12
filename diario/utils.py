"""Fuso horário e formatação."""
from datetime import date, datetime, timedelta, timezone

from flask import current_app


def tz():
    nome = current_app.config.get("TZ", "America/Bahia")
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nome)
    except Exception:  # sem base de fusos instalada (ex.: Windows sem tzdata)
        return timezone(timedelta(hours=-3))


def para_local(iso_utc):
    if not iso_utc:
        return None
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(tz())


def hoje_local() -> date:
    return datetime.now(tz()).date()


def f_dt(iso_utc):
    d = para_local(iso_utc)
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def f_data(iso_data):
    try:
        return datetime.strptime(iso_data, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return "—"


def f_dec(v, casas=1):
    if v is None:
        return "—"
    return f"{v:.{casas}f}".replace(".", ",")


def atraso_dias(data_ref, criado_em_utc) -> int:
    """Dias entre a data do RDO e o dia em que ele foi efetivamente registrado."""
    criado = para_local(criado_em_utc).date()
    return (criado - datetime.strptime(data_ref, "%Y-%m-%d").date()).days
