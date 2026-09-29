"""Constants for Playnite Connect Companion."""

DOMAIN = "playnite_connect"

CONF_DEVICE_ID = "device_id"
CONF_CACHE_COVERS = "cache_covers"
CONF_COVER_TRANSPORT = "cover_transport"
CONF_COVER_API_URL = "cover_api_url"
# Configuration-dictionary key; it never contains an actual token.
CONF_COVER_API_TOKEN = "cover_api_token"  # nosec B105

DATA_DEVICE_ID = "device_id"
DATA_LIBRARY = "library"
DATA_CACHE_COVERS = "cache_covers"
DATA_COVER_TRANSPORT = "cover_transport"
DATA_COVER_API_URL = "cover_api_url"
# Configuration-dictionary key; it never contains an actual token.
DATA_COVER_API_TOKEN = "cover_api_token"  # nosec B105

PLATFORMS = ["media_player", "sensor", "select", "image"]

DEFAULT_NAME = "Playnite Connect"
MQTT_TOPIC_PREFIX = "playnite"
PROTOCOL_VERSION = 1

LIBRARY_REQUEST_TOPIC = "library/request"
LIBRARY_COMMAND_TOPIC = "library/command"
LIBRARY_RESPONSE_TOPIC = "library/response"
LIBRARY_MANIFEST_TOPIC = "library/manifest"
LIBRARY_CHUNK_TOPIC = "library/chunk"
LIBRARY_UPDATE_TOPIC = "library/update"
LIBRARY_STATUS_TOPIC = "library/status"
LIBRARY_COVER_REQUEST_TOPIC = "library/cover/request"
LIBRARY_COVER_CHUNK_TOPIC = "library/cover/chunk"
