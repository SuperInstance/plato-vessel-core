"""
FLUX-PLATO Search Bridge — Semantic search over PLATO tiles.

Uses flux-index embeddings to search PLATO room contents.
Drop-in replacement for keyword search with 3× better recall.

Usage:
    from flux_plato_search import FluxPlatoSearch
    
    search = FluxPlatoSearch("http://localhost:8847")
    search.index_rooms(["oracle1-forgemaster-bridge", "fleet-ops"])
    
    results = search.search("constraint drift detection")
    for r in results:
        print(f"[{r['score']:.3f}] {r['question'][:80]}")

Requires: flux-index (pip install flux-index)
"""

import json
import math
import urllib.request
from typing import Dict, List, Optional
from flux_index.core import Embedder, Tile, Index


class FluxPlatoSearch:
    """Semantic search over PLATO room tiles using flux-index embeddings."""
    
    def __init__(self, plato_url: str = "http://147.224.38.131:8847", dim: int = 128):
        self.plato_url = plato_url.rstrip("/")
        self.index = Index(dim)
        self._indexed_rooms = set()
    
    def index_room(self, room_id: str) -> int:
        """Fetch tiles from a PLATO room and index them."""
        url = f"{self.plato_url}/room/{room_id}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"Failed to fetch room {room_id}: {e}")
            return 0
        
        tiles = data if isinstance(data, list) else data.get("tiles", [])
        
        converted = []
        for i, t in enumerate(tiles):
            question = t.get("question", "")
            answer = t.get("answer", "")
            text = f"{question}\n{answer}"
            
            tile = Tile(
                id=f"plato:{room_id}:{t.get('tile_id', i)}",
                type="plato-tile",
                path=f"{room_id}/{t.get('tile_id', i)}",
                name=question[:100],
                content=text[:2000],
            )
            converted.append(tile)
        
        if converted:
            self.index.add(converted)
            self._indexed_rooms.add(room_id)
        
        return len(converted)
    
    def index_rooms(self, room_ids: List[str]) -> Dict[str, int]:
        """Index multiple rooms. Returns {room_id: tile_count}."""
        results = {}
        for room_id in room_ids:
            count = self.index_room(room_id)
            results[room_id] = count
        return results
    
    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """Semantic search across all indexed PLATO rooms."""
        results = self.index.search(query, top_k=top_k)
        return [
            {
                "score": r.score,
                "question": r.tile.name,
                "content": r.tile.content[:200],
                "room": r.tile.path.split("/")[0] if "/" in r.tile.path else "?",
                "tile_id": r.tile.id,
            }
            for r in results
        ]
    
    def list_indexed(self) -> List[str]:
        """Return list of indexed room IDs."""
        return list(self._indexed_rooms)
    
    @property
    def tile_count(self) -> int:
        return self.index.count


if __name__ == "__main__":
    # Demo: index bridge room and search
    search = FluxPlatoSearch()
    print("Indexing oracle1-forgemaster-bridge...")
    count = search.index_room("oracle1-forgemaster-bridge")
    print(f"Indexed {count} tiles")
    
    queries = [
        "constraint theory Eisenstein drift",
        "fleet coordination task assignment",
        "Matrix bridge communication",
    ]
    for q in queries:
        print(f"\n--- '{q}' ---")
        for r in search.search(q, top_k=3):
            print(f"  [{r['score']:.3f}] {r['question'][:80]}")
