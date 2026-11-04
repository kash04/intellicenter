"""Constants for the Pentair IntelliCenter integration."""

from __future__ import annotations

from typing import Literal

# UnitOfRatio only exists on Home Assistant >= 2026.7, while the legacy
# CONCENTRATION_PARTS_PER_MILLION constant is deprecated there (removal in
# 2027.8) but is all that older supported cores provide.
try:
    from homeassistant.const import UnitOfRatio

    CONCENTRATION_PPM = UnitOfRatio.PARTS_PER_MILLION
except ImportError:  # Home Assistant < 2026.7
    from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION

    CONCENTRATION_PPM = CONCENTRATION_PARTS_PER_MILLION

# Integration domain
DOMAIN = "intellicenter"

# Units of measurement (not available in Home Assistant constants)
CONST_RPM = "rpm"  # revolutions per minute
CONST_GPM = "gpm"  # gallons per minute

CALIB_ATTR = "CALIB"  # not yet in pyintellicenter
DNTSTP_ATTR = "DNTSTP"  # not yet in pyintellicenter
LIMIT_ATTR = "LIMIT"  # not yet in pyintellicenter
MANHT_ATTR = "MANHT"  # not yet in pyintellicenter
PORT_ATTR = "PORT"  # not yet in pyintellicenter
PRIMFLO_ATTR = "PRIMFLO"  # not yet in pyintellicenter
PRIMTIM_ATTR = "PRIMTIM"  # not yet in pyintellicenter
PROBE_ATTR = "PROBE"  # not yet in pyintellicenter
SINGLE_ATTR = "SINGLE"  # not yet in pyintellicenter

# IntelliCenter CHEM object subtypes
CHLORINATOR_SUBTYPE = "ICHLOR"
CHEM_CONTROLLER_SUBTYPE = "ICHEM"

# IntelliChlor problem flags. pyintellicenter 0.3.2 does not export these names.
# The panel reports them as ON/OFF on a CHEM object whose subtype is ICHLOR.
# No Flow is not one of these keys; it arrives as a STATUS alert object.
COMERR_ATTR = "COMERR"  # communication lost
SALTLO_ATTR = "SALTLO"  # low salt
VERYLO_ATTR = "VERYLO"  # very low salt
CUTOFF_ATTR = "CUTOFF"  # cold water cutoff
CLEAN_ATTR = "CLEAN"  # clean / inspect cell
CHLORINATOR_PROBLEM_ATTRS: tuple[str, ...] = (
    COMERR_ATTR,
    SALTLO_ATTR,
    VERYLO_ATTR,
    CUTOFF_ATTR,
    CLEAN_ATTR,
)

# Controller alert rows (OBJTYP=STATUS). pyintellicenter 0.3.2 has no STATUS type.
STATUS_OBJECT_TYPE = "STATUS"
COUNT_ATTR = "COUNT"  # occurrences
PARTY_ATTR = "PARTY"  # epoch seconds of the last occurrence

# How often to re-read active controller alerts. Objects already in the model
# are push-subscribed; this interval discovers alerts that appear or clear later.
ALERT_REFRESH_INTERVAL = 30

# Configuration option keys
CONF_KEEPALIVE_INTERVAL = "keepalive_interval"
CONF_RECONNECT_DELAY = "reconnect_delay"
CONF_TRANSPORT = "transport"

# Transport type values
TRANSPORT_TCP = "tcp"
TRANSPORT_WEBSOCKET = "websocket"
TransportType = Literal["tcp", "websocket"]

# Default values for configuration options
DEFAULT_KEEPALIVE_INTERVAL = 90  # seconds
DEFAULT_RECONNECT_DELAY = 30  # seconds
DEFAULT_TRANSPORT = "tcp"  # type: TransportType

# Minimum/maximum values for configuration options
MIN_KEEPALIVE_INTERVAL = 30
MAX_KEEPALIVE_INTERVAL = 300
MIN_RECONNECT_DELAY = 10
MAX_RECONNECT_DELAY = 120
