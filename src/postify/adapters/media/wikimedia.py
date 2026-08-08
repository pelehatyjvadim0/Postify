import httpx


class WikimediaImageSearch:
    def __init__(self, *, client: httpx.Client):
        self.client = client

    def search(self, query):
        try:
            data = self.client.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": query,
                    "prop": "imageinfo",
                    "iiprop": "url",
                },
            ).json()
            page = next(iter(data.get("query", {}).get("pages", {}).values()), {})
            url = page.get("imageinfo", [{}])[0].get("url")
            return ("wikimedia", url) if url else None
        except (httpx.HTTPError, ValueError, KeyError):
            return None
