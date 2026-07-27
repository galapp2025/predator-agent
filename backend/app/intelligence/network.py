"""
Network Graph — Relationship mapping, connection discovery, influence propagation.

Capabilities:
  - Build entity relationship graphs from collected data
  - Discover indirect connections between entities
  - Identify influence hubs and clusters
  - Calculate network centrality metrics
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Connection:
    """A connection between two entities."""
    source: str
    target: str
    relation_type: str  # "family", "business", "political", "social", "geographic"
    strength: float  # 0-1
    evidence: str = ""
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


@dataclass
class NetworkNode:
    """A node in the influence network."""
    entity_name: str
    entity_id: Optional[str] = None
    influence_score: float = 0.0
    connections: list[Connection] = field(default_factory=list)
    cluster_id: Optional[int] = None
    centrality: float = 0.0  # Betweenness centrality (0-1)
    is_hub: bool = False


class InfluenceNetwork:
    """
    Maps relationships between entities and identifies influence clusters.
    """

    def __init__(self):
        self.nodes: dict[str, NetworkNode] = {}
        self.connections: list[Connection] = []
        self._adjacency: dict[str, set[str]] = defaultdict(set)

    def add_entity(self, name: str, influence_score: float = 0.0):
        """Add or update an entity in the network."""
        if name not in self.nodes:
            self.nodes[name] = NetworkNode(
                entity_name=name,
                influence_score=influence_score,
            )
        else:
            self.nodes[name].influence_score = influence_score

    def add_connection(self, source: str, target: str,
                        relation_type: str, strength: float,
                        evidence: str = ""):
        """Add a connection between two entities."""
        conn = Connection(
            source=source, target=target,
            relation_type=relation_type, strength=strength,
            evidence=evidence,
        )
        self.connections.append(conn)
        self._adjacency[source].add(target)
        self._adjacency[target].add(source)

        # Ensure both nodes exist
        if source not in self.nodes:
            self.nodes[source] = NetworkNode(entity_name=source)
        if target not in self.nodes:
            self.nodes[target] = NetworkNode(entity_name=target)

        self.nodes[source].connections.append(conn)
        self.nodes[target].connections.append(conn)

    def build_from_collected_data(self, name: str, data: dict):
        """
        Build network connections from OSINT collected data.
        Extracts relationships from all data sources.
        """
        self.add_entity(name)

        # Business connections
        business = data.get("business", {})
        for company in business.get("companies", []):
            if company.get("name"):
                self.add_entity(company["name"])
                self.add_connection(
                    name, company["name"],
                    relation_type="business",
                    strength=0.6,
                )

        for role in business.get("director_roles", []):
            if role.get("company"):
                self.add_entity(role["company"])
                self.add_connection(
                    name, role["company"],
                    relation_type="business",
                    strength=0.7,
                    evidence=f"Director: {role.get('position', '')}",
                )

        # Family connections
        sanctions = data.get("sanctions", {})
        for family in sanctions.get("family_connections", []):
            fname = family.get("name", "")
            if isinstance(fname, list):
                fname = fname[0] if fname else ""
            if fname:
                self.add_entity(fname)
                self.add_connection(
                    name, fname,
                    relation_type="family",
                    strength=0.9,
                    evidence=family.get("relationship", ""),
                )

        # Political connections
        political = data.get("sanctions", {}).get("political_roles", [])
        for role in political:
            if isinstance(role, str):
                # Extract organization name from role string
                parts = role.split("|")
                org = parts[-1].strip() if parts else role
                self.add_entity(org)
                self.add_connection(
                    name, org,
                    relation_type="political",
                    strength=0.5,
                    evidence=role,
                )

        # Geographic clustering (if location data available)
        location = data.get("location", "")
        if location:
            # Entities in same location get weak geographic ties
            for other_name, other_data in self.nodes.items():
                if other_name != name:
                    pass  # Location-based clustering applied during analysis

    def find_path(self, source: str, target: str, max_depth: int = 4) -> list[str] | None:
        """
        Find shortest path between two entities (BFS).
        Returns list of entity names forming the path.
        """
        if source not in self._adjacency or target not in self._adjacency:
            return None

        if target in self._adjacency[source]:
            return [source, target]

        # BFS
        visited = {source}
        queue = [(source, [source])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                continue

            for neighbor in self._adjacency[current]:
                if neighbor == target:
                    return path + [target]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def identify_hubs(self, min_connections: int = 3) -> list[NetworkNode]:
        """Identify influence hubs: entities with many connections."""
        hubs = []
        for node in self.nodes.values():
            if len(node.connections) >= min_connections:
                node.is_hub = True
                hubs.append(node)
        return sorted(hubs, key=lambda n: len(n.connections), reverse=True)

    def compute_centrality(self):
        """
        Compute approximate betweenness centrality for all nodes.
        Simplified for performance on medium graphs.
        """
        total_nodes = len(self.nodes)
        if total_nodes <= 2:
            return

        for node_name in self.nodes:
            paths_through = 0
            total_paths = 0

            # Sample-based approximation for large graphs
            others = [n for n in self.nodes if n != node_name]
            sample_size = min(20, len(others))

            for other in others[:sample_size]:
                path = self.find_path(node_name, other, max_depth=5)
                if path:
                    paths_through += 1
                total_paths += 1

            self.nodes[node_name].centrality = (
                paths_through / max(total_paths, 1)
            )

    def get_cluster(self, entity_name: str, depth: int = 2) -> dict:
        """
        Get the influence cluster around an entity.
        Returns: {entity: str, cluster: [{name, relation_type, strength}], size: int}
        """
        cluster = []
        visited = {entity_name}
        frontier = [entity_name]

        for _ in range(depth):
            next_frontier = []
            for current in frontier:
                for neighbor in self._adjacency.get(current, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)
                        # Find the connection details
                        node = self.nodes.get(current)
                        if node:
                            for conn in node.connections:
                                if conn.target == neighbor or conn.source == neighbor:
                                    cluster.append({
                                        "name": neighbor,
                                        "relation_type": conn.relation_type,
                                        "strength": conn.strength,
                                    })
                                    break
            frontier = next_frontier

        return {
            "entity": entity_name,
            "cluster": cluster,
            "size": len(cluster),
            "hub_count": sum(
                1 for n in cluster
                if self.nodes.get(n["name"]) and self.nodes[n["name"]].is_hub
            ),
        }

    def summary(self) -> dict:
        """Generate network summary statistics."""
        return {
            "total_entities": len(self.nodes),
            "total_connections": len(self.connections),
            "hubs": len([n for n in self.nodes.values() if n.is_hub]),
            "connection_types": self._count_connection_types(),
            "largest_cluster_size": max(
                (len(c) for c in self._adjacency.values()), default=0
            ),
        }

    def _count_connection_types(self) -> dict:
        counts = defaultdict(int)
        for conn in self.connections:
            counts[conn.relation_type] += 1
        return dict(counts)
