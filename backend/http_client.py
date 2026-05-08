import httpx
import logging

logger = logging.getLogger(__name__)

class HttpClientManager:
    _client: httpx.AsyncClient = None

    @classmethod
    async def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            logger.info("Initializing global AsyncClient...")
            cls._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)
            )
        return cls._client

    @classmethod
    async def close_client(cls):
        if cls._client and not cls._client.is_closed:
            logger.info("Closing global AsyncClient...")
            await cls._client.aclose()
            cls._client = None
