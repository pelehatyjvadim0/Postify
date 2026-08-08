import httpx


class WikimediaImageSearch:
    def __init__(self, *, client: httpx.Client):
        self.client = client

    def search(self, query):
        try:
            data = self.client.get(
                "https://commons.wikimedia.org/w/api.php",
                headers={"User-Agent": "Postify/0.1"},
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": query,
                    "gsrnamespace": "6",
                    "prop": "imageinfo",
                    "iiprop": "url|mime",
                },
            ).json()
            if not isinstance(data, dict):
                return None
            query_data = data.get("query", {})
            if not isinstance(query_data, dict):
                return None
            pages = query_data.get("pages", {})
            if not isinstance(pages, dict):
                return None
            for page in pages.values():
                if not isinstance(page, dict):
                    continue
                imageinfo = page.get("imageinfo", [])
                if not isinstance(imageinfo, list):
                    continue
                for image in imageinfo:
                    if not isinstance(image, dict):
                        continue
                    url = image.get("url")
                    if (
                        isinstance(url, str)
                        and url
                        and image.get("mime") in {"image/jpeg", "image/png", "image/webp"}
                    ):
                        return ("wikimedia", url)
            return None
        except (httpx.HTTPError, ValueError, KeyError):
            return None
