# -*- coding: utf-8 -*-
"""
Conversiones seguras y utilidades de parsing comunes.
Módulo canónico — todas las conversiones deben importarse desde aquí.
"""
import json
from datetime import date, datetime


def safe_float(val, default=0.0):
    """Convierte a float de forma segura. '' o None → default."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """Convierte a int de forma segura. '' o None → default."""
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def is_present(value):
    """Retorna True si el valor no es None, cadena vacía, ni 'unknown'."""
    if value is None:
        return False
    s = str(value).strip().lower()
    return s not in ("", "none", "unknown", "desconocido", "null")


def is_truthy(value):
    """Retorna True si el valor representa afirmación (si, yes, true, 1, on)."""
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("si", "sí", "yes", "true", "1", "on")


def safe_bool(value, default=None):
    """Coerce explícitamente bool desde bool/int/str; retorna default si es ambiguo."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return default
    s = str(value).strip().lower()
    if s in ("si", "sí", "yes", "true", "1", "on"):
        return True
    if s in ("no", "false", "0", "off"):
        return False
    return default


def parse_json_blob(value, default=None):
    """Parsea un campo JSON almacenado como TEXT en SQLite."""
    if default is None:
        default = {}
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def json_blob(value):
    """Serializa un dict/list a JSON string para almacenamiento."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def parse_date(value):
    """Parsea una fecha en formato YYYY-MM-DD. Retorna None si falla."""
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None
