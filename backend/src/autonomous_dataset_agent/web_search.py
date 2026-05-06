from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import Counter
from urllib import error, parse, request

from .config import SourceConfig
from .contracts import SourceRecord
from .downloaders import build_source_id, extract_domain, normalize_url


class ImageSearchProvider(ABC):
    name: str

    @abstractmethod
    def search_images(
        self,
        query: str,
        limit: int,
        config: SourceConfig,
    ) -> list[dict[str, object]]:
        raise NotImplementedError


class DuckDuckGoImageSearchProvider(ImageSearchProvider):
    name = "duckduckgo"

    def search_images(self, query: str, limit: int, config: SourceConfig) -> list[dict[str, object]]:
        vqd = self._fetch_vqd(query, config)
        encoded_query = parse.quote(query)
        endpoint = (
            "https://duckduckgo.com/i.js"
            f"?l=us-en&o=json&q={encoded_query}&vqd={parse.quote(vqd)}&f=,,,&p=1"
        )
        http_request = request.Request(
            endpoint,
            headers={"User-Agent": config.download_user_agent, "Referer": "https://duckduckgo.com/"},
        )
        try:
            with request.urlopen(http_request, timeout=config.download_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"DuckDuckGo image search failed: {exc}") from exc

        results: list[dict[str, object]] = []
        for item in payload.get("results", [])[:limit]:
            image_url = item.get("image")
            if not image_url:
                continue
            results.append(
                {
                    "url": str(image_url),
                    "title": str(item.get("title") or item.get("source") or query),
                    "domain": str(item.get("source") or extract_domain(str(image_url))),
                    "source_page": str(item.get("url") or image_url),
                }
            )
        return results

    @staticmethod
    def _fetch_vqd(query: str, config: SourceConfig) -> str:
        endpoint = f"https://duckduckgo.com/?q={parse.quote(query)}&iax=images&ia=images"
        http_request = request.Request(
            endpoint,
            headers={"User-Agent": config.download_user_agent},
        )
        try:
            with request.urlopen(http_request, timeout=config.download_timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="ignore")
        except error.URLError as exc:
            raise RuntimeError(f"DuckDuckGo bootstrap failed: {exc}") from exc

        match = re.search(r"vqd=['\"]([^'\"]+)['\"]", body)
        if not match:
            match = re.search(r'vqd=\\?"([^"]+)', body)
        if not match:
            raise RuntimeError("DuckDuckGo bootstrap token was not found.")
        return match.group(1)


class BingImageSearchProvider(ImageSearchProvider):
    name = "bing"

    def search_images(self, query: str, limit: int, config: SourceConfig) -> list[dict[str, object]]:
        if not config.bing_search_api_key:
            raise RuntimeError("BING_SEARCH_API_KEY is not configured.")

        endpoint = (
            "https://api.bing.microsoft.com/v7.0/images/search"
            f"?q={parse.quote(query)}&count={limit}"
        )
        http_request = request.Request(
            endpoint,
            headers={
                "User-Agent": config.download_user_agent,
                "Ocp-Apim-Subscription-Key": config.bing_search_api_key,
            },
        )
        try:
            with request.urlopen(http_request, timeout=config.download_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Bing image search failed: {exc}") from exc

        results: list[dict[str, object]] = []
        for item in payload.get("value", [])[:limit]:
            content_url = item.get("contentUrl")
            if not content_url:
                continue
            results.append(
                {
                    "url": str(content_url),
                    "title": str(item.get("name") or query),
                    "domain": str(item.get("hostPageDisplayUrl") or extract_domain(str(content_url))),
                    "source_page": str(item.get("hostPageUrl") or content_url),
                }
            )
        return results


def build_web_search_providers(config: SourceConfig) -> list[ImageSearchProvider]:
    provider_map: dict[str, ImageSearchProvider] = {
        "duckduckgo": DuckDuckGoImageSearchProvider(),
        "bing": BingImageSearchProvider(),
    }
    providers: list[ImageSearchProvider] = []
    for name in config.web_search_provider_order or ["duckduckgo", "bing"]:
        normalized = name.strip().lower()
        provider = provider_map.get(normalized)
        if provider is not None:
            providers.append(provider)
    return providers


def _is_domain_allowed(domain: str, config: SourceConfig) -> bool:
    allowlist = set(config.source_domain_allowlist or [])
    denylist = set(config.source_domain_denylist or [])
    if allowlist and domain not in allowlist:
        return False
    if denylist and domain in denylist:
        return False
    return True


def search_web_image_candidates(
    classes: list[str],
    queries_by_class: dict[str, list[str]],
    config: SourceConfig,
) -> tuple[dict[str, list[SourceRecord]], list[str]]:
    providers = build_web_search_providers(config)
    provider_priority = {provider.name: index for index, provider in enumerate(providers)}
    notes: list[str] = []
    grouped: dict[str, list[SourceRecord]] = {}

    for class_name in classes:
        seen_urls: set[str] = set()
        candidates: list[SourceRecord] = []
        queries = queries_by_class.get(class_name, [])

        for query_index, query in enumerate(queries):
            query_results: list[dict[str, object]] = []
            selected_provider_name = "unknown"
            for provider in providers:
                try:
                    query_results = provider.search_images(
                        query,
                        config.web_image_search_results_per_class,
                        config,
                    )
                except RuntimeError as exc:
                    notes.append(f"Web search provider {provider.name} failed for '{query}': {exc}")
                    continue
                if query_results:
                    selected_provider_name = provider.name
                    break

            for result_index, result in enumerate(query_results):
                image_url = str(result["url"])
                normalized_url = normalize_url(image_url)
                domain = extract_domain(str(result.get("source_page") or image_url))
                if normalized_url in seen_urls or not _is_domain_allowed(domain, config):
                    continue

                source = SourceRecord(
                    id=build_source_id("web", class_name, normalized_url),
                    source_type="web_image",
                    class_names=[class_name],
                    title=str(result.get("title") or class_name),
                    url=image_url,
                    local_path=None,
                    metadata={
                        "provider": selected_provider_name,
                        "query": query,
                        "domain": domain,
                        "rank": result_index,
                        "source_page": result.get("source_page"),
                        "query_index": query_index,
                    },
                )
                candidates.append(source)
                seen_urls.add(normalized_url)

        domain_counts = Counter(str(candidate.metadata.get("domain", "")) for candidate in candidates)
        candidates.sort(
            key=lambda candidate: (
                provider_priority.get(str(candidate.metadata.get("provider")), len(provider_priority)),
                int(candidate.metadata.get("query_index", 999)),
                max(0, domain_counts.get(str(candidate.metadata.get("domain", "")), 0) - 1),
                int(candidate.metadata.get("rank", 999)),
                candidate.id,
            )
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate.metadata["rank"] = rank

        grouped[class_name] = candidates[: config.web_image_search_results_per_class]

    return grouped, notes
