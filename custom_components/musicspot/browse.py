"""Browse model: turns the Spotify library into pages of 6 rows for a panel.

Each panel has its own Browser (path stack + page). The panel only sees row
numbers (D11); rows keep the Spotify URIs needed to open, play or queue them.
Folders (playlists, albums) start with a "Play" row so the whole context can be
played, and so playlists Spotify won't list (not owned) can still be played (D16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .api import MusicSpotApi, SpotifyForbiddenError, SpotifyNotFoundError

PAGE_SIZE = 6
_RECENT_LIMIT = 50


@dataclass
class Node:
    """A level in the browse tree."""

    kind: str  # root | playlists | playlist | liked | albums | album | recent
    title: str
    id: str = ""
    context_uri: str = ""  # what "Play" plays, and the context for its tracks
    image: str | None = None  # cover to reuse for rows without their own image
    page: int = 1
    cache: list[dict[str, Any]] | None = None  # cursor-based lists (recently played)
    notice: str = ""  # shown as subtitle of the Play row (e.g. items not listable)


@dataclass
class Row:
    """One row on the panel."""

    title: str
    subtitle: str = ""
    image: str | None = None
    open: Node | None = None  # folder: drill in
    uri: str = ""  # playable item (track/episode)
    context_uri: str = ""  # play `uri` inside this context; or the context itself
    play_all: bool = False


@dataclass
class Page:
    """What `show_page` needs."""

    title: str
    page: int
    pages: int
    can_back: bool
    rows: list[Row] = field(default_factory=list)


def _pick_thumb(images: list[dict[str, Any]] | None, size: int = 48) -> str | None:
    """Smallest image at least `size` px (Spotify sends 640/300/64)."""
    candidates = [i for i in images or [] if i.get("url")]
    if not candidates:
        return None
    big_enough = [i for i in candidates if (i.get("width") or 0) >= size]
    pool = big_enough or candidates
    pick = min if big_enough else max
    return pick(pool, key=lambda i: i.get("width") or 0)["url"]


def _track_row(track: dict[str, Any] | None, context_uri: str, fallback_image: str | None) -> Row | None:
    """Row for a track or episode object (None for unavailable/local items)."""
    if not track or not track.get("uri"):
        return None
    if track.get("type") == "episode":
        subtitle = (track.get("show") or {}).get("name", "")
        image = _pick_thumb(track.get("images")) or fallback_image
    else:
        subtitle = ", ".join(a.get("name", "") for a in track.get("artists", []))
        image = _pick_thumb((track.get("album") or {}).get("images")) or fallback_image
    return Row(
        title=track.get("name", "?"),
        subtitle=subtitle,
        image=image,
        uri=track["uri"],
        context_uri=context_uri,
    )


class Browser:
    """Browse state for one panel."""

    def __init__(self, api: MusicSpotApi, user_id: str) -> None:
        """Start at the library root."""
        self._api = api
        self._user_id = user_id
        self._stack: list[Node] = [Node("root", "Library")]
        self.rows: list[Row] = []

    @property
    def node(self) -> Node:
        """Current level."""
        return self._stack[-1]

    def open(self, node: Node) -> None:
        """Drill into a folder."""
        self._stack.append(node)

    def back(self) -> bool:
        """Go up one level; False at the root."""
        if len(self._stack) == 1:
            return False
        self._stack.pop()
        return True

    def turn_page(self, delta: int) -> None:
        """Move to the previous/next page (clamped when loading)."""
        self.node.page = max(1, self.node.page + delta)

    async def async_load(self) -> Page:
        """Fetch the current page from Spotify."""
        node = self.node
        loader = getattr(self, f"_load_{node.kind}")
        rows, total = await loader(node)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        if node.page > pages:
            node.page = pages
            rows, total = await loader(node)
        self.rows = rows
        return Page(
            title=node.title,
            page=node.page,
            pages=pages,
            can_back=len(self._stack) > 1,
            rows=rows,
        )

    # ---- paging helpers -------------------------------------------------

    @staticmethod
    def _window(node: Node, header_rows: int) -> tuple[int, int, int]:
        """For the current page return (rows of header to show, API offset, API limit).

        The virtual list is `header_rows` fixed rows followed by the API items.
        """
        start = (node.page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        header = max(0, min(end, header_rows) - start)
        offset = max(0, start - header_rows)
        limit = PAGE_SIZE - header
        return header, offset, limit

    def _play_row(self, node: Node) -> Row:
        return Row(
            title="Play all",
            subtitle=node.notice or node.title,
            image=node.image,
            context_uri=node.context_uri,
            play_all=True,
        )

    # ---- loaders: return (rows, virtual total) ----------------------------

    async def _load_root(self, node: Node) -> tuple[list[Row], int]:
        rows = [
            Row("Playlists", "Your playlists", open=Node("playlists", "Playlists")),
            Row(
                "Liked Songs",
                "Your saved tracks",
                open=Node(
                    "liked",
                    "Liked Songs",
                    context_uri=f"spotify:user:{self._user_id}:collection",
                ),
            ),
            Row("Albums", "Your saved albums", open=Node("albums", "Albums")),
            Row("Recently played", "", open=Node("recent", "Recently played")),
        ]
        return rows, len(rows)

    async def _load_playlists(self, node: Node) -> tuple[list[Row], int]:
        _, offset, limit = self._window(node, 0)
        data = await self._api.get_playlists(limit, offset)
        rows = []
        for pl in data.get("items") or []:
            if not pl or not pl.get("id"):
                continue
            count = (pl.get("items") or pl.get("tracks") or {}).get("total")
            owner = (pl.get("owner") or {}).get("display_name") or ""
            image = _pick_thumb(pl.get("images"))
            rows.append(
                Row(
                    title=pl.get("name") or "?",
                    subtitle=f"{count} songs" if count is not None else owner,
                    image=image,
                    open=Node(
                        "playlist",
                        pl.get("name") or "Playlist",
                        id=pl["id"],
                        context_uri=pl.get("uri") or f"spotify:playlist:{pl['id']}",
                        image=image,
                    ),
                )
            )
        return rows, int(data.get("total") or len(rows))

    async def _load_playlist(self, node: Node) -> tuple[list[Row], int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        if limit <= 0:
            return rows, 1
        try:
            data = await self._api.get_playlist_items(node.id, limit, offset)
        except (SpotifyForbiddenError, SpotifyNotFoundError):
            # Since Feb 2026 only owned/collaborative playlists list their items.
            node.notice = "Spotify only lists songs of your own playlists"
            return [self._play_row(node)], 1
        for entry in data.get("items") or []:
            row = _track_row(
                (entry or {}).get("item") or (entry or {}).get("track"),
                node.context_uri,
                node.image,
            )
            if row:
                rows.append(row)
        return rows, 1 + int(data.get("total") or 0)

    async def _load_liked(self, node: Node) -> tuple[list[Row], int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        data = await self._api.get_saved_tracks(max(limit, 1), offset)
        if limit > 0:
            for entry in data.get("items") or []:
                row = _track_row((entry or {}).get("track"), node.context_uri, None)
                if row:
                    rows.append(row)
        return rows, 1 + int(data.get("total") or 0)

    async def _load_albums(self, node: Node) -> tuple[list[Row], int]:
        _, offset, limit = self._window(node, 0)
        data = await self._api.get_saved_albums(limit, offset)
        rows = []
        for entry in data.get("items") or []:
            album = (entry or {}).get("album") or {}
            if not album.get("id"):
                continue
            image = _pick_thumb(album.get("images"))
            artists = ", ".join(a.get("name", "") for a in album.get("artists", []))
            rows.append(
                Row(
                    title=album.get("name") or "?",
                    subtitle=artists,
                    image=image,
                    open=Node(
                        "album",
                        album.get("name") or "Album",
                        id=album["id"],
                        context_uri=album.get("uri") or f"spotify:album:{album['id']}",
                        image=image,
                    ),
                )
            )
        return rows, int(data.get("total") or len(rows))

    async def _load_album(self, node: Node) -> tuple[list[Row], int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        data = await self._api.get_album_tracks(node.id, max(limit, 1), offset)
        if limit > 0:
            for track in data.get("items") or []:
                row = _track_row(track, node.context_uri, node.image)
                if row:
                    rows.append(row)
        return rows, 1 + int(data.get("total") or 0)

    async def _load_recent(self, node: Node) -> tuple[list[Row], int]:
        if node.cache is None:
            # Cursor-based endpoint: fetch once when opened, then page locally.
            data = await self._api.get_recently_played(_RECENT_LIMIT)
            seen: set[str] = set()
            node.cache = []
            for entry in data.get("items") or []:
                track = (entry or {}).get("track") or {}
                if track.get("uri") and track["uri"] not in seen:
                    seen.add(track["uri"])
                    node.cache.append(entry)
        start = (node.page - 1) * PAGE_SIZE
        rows = []
        for entry in node.cache[start : start + PAGE_SIZE]:
            context = (entry.get("context") or {}).get("uri") or ""
            row = _track_row(entry.get("track"), context, None)
            if row:
                rows.append(row)
        return rows, len(node.cache)
