"""BPMN 2.0 parser and token-based process executor.

Supports startEvent, endEvent, userTask, serviceTask, exclusiveGateway,
parallelGateway, sequenceFlow with optional conditionExpression.
Also executes the JSON graph stored on WorkflowTemplate.graph.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
}


@dataclass
class Node:
    id: str
    type: str
    name: str = ""
    assignee_role: str | None = None
    assignee_id: int | None = None
    action: str | None = None
    due_days: int | None = None


@dataclass
class Edge:
    source: str
    target: str
    condition: str | None = None


@dataclass
class ProcessDef:
    id: str
    name: str
    nodes: dict[str, Node] = field(default_factory=dict)
    outgoing: dict[str, list[Edge]] = field(default_factory=dict)
    start: str | None = None


def parse_bpmn_xml(xml_text: str) -> ProcessDef:
    root = ET.fromstring(xml_text)
    proc = root.find("bpmn:process", NS)
    if proc is None:
        proc = root.find("{http://www.omg.org/spec/BPMN/20100524/MODEL}process")
    if proc is None:
        # bare process
        proc = root if root.tag.endswith("process") else None
    if proc is None:
        raise ValueError("No BPMN process element")
    pid = proc.attrib.get("id") or "process"
    pname = proc.attrib.get("name") or pid
    definition = ProcessDef(id=pid, name=pname)
    tag_map = {
        "startEvent": "start",
        "endEvent": "end",
        "userTask": "userTask",
        "serviceTask": "serviceTask",
        "exclusiveGateway": "exclusiveGateway",
        "parallelGateway": "parallelGateway",
        "task": "userTask",
    }
    for child in list(proc):
        local = child.tag.split("}")[-1]
        if local == "sequenceFlow":
            edge = Edge(
                source=child.attrib.get("sourceRef") or "",
                target=child.attrib.get("targetRef") or "",
                condition=_text(child.find("bpmn:conditionExpression", NS))
                or _text(child.find("{http://www.omg.org/spec/BPMN/20100524/MODEL}conditionExpression")),
            )
            definition.outgoing.setdefault(edge.source, []).append(edge)
            continue
        kind = tag_map.get(local)
        if not kind:
            continue
        nid = child.attrib.get("id") or local
        node = Node(
            id=nid,
            type=kind,
            name=child.attrib.get("name") or nid,
            assignee_role=child.attrib.get("assigneeRole") or child.attrib.get("camunda:assignee"),
            action=child.attrib.get("action"),
        )
        definition.nodes[nid] = node
        if kind == "start" and not definition.start:
            definition.start = nid
    if not definition.start:
        for n in definition.nodes.values():
            if n.type == "start":
                definition.start = n.id
                break
    return definition


def from_graph_json(graph: dict, steps: list | None = None) -> ProcessDef:
    nodes_raw = (graph or {}).get("nodes") or []
    edges_raw = (graph or {}).get("edges") or []
    definition = ProcessDef(id="graph", name=graph.get("name") or "graph")
    if not nodes_raw and steps:
        for i, s in enumerate(steps):
            nid = str(s.get("id") if isinstance(s, dict) else i)
            name = s.get("name") if isinstance(s, dict) else str(s)
            definition.nodes[nid] = Node(
                id=nid,
                type="userTask",
                name=name,
                assignee_role=(s.get("assignee_role") if isinstance(s, dict) else None),
                assignee_id=(s.get("assignee_id") if isinstance(s, dict) else None),
                action=(s.get("action") if isinstance(s, dict) else None),
                due_days=(s.get("due_days") if isinstance(s, dict) else None),
            )
        ids = list(definition.nodes)
        if ids:
            definition.start = ids[0]
            for a, b in zip(ids, ids[1:]):
                definition.outgoing.setdefault(a, []).append(Edge(a, b))
        return definition
    for n in nodes_raw:
        nid = str(n.get("id"))
        definition.nodes[nid] = Node(
            id=nid,
            type=n.get("type") or n.get("kind") or "userTask",
            name=n.get("name") or nid,
            assignee_role=n.get("assignee_role"),
            assignee_id=n.get("assignee_id"),
            action=n.get("action"),
            due_days=n.get("due_days"),
        )
        if definition.nodes[nid].type in ("start", "startEvent"):
            definition.start = nid
    for e in edges_raw:
        src = str(e.get("from") or e.get("source"))
        tgt = str(e.get("to") or e.get("target"))
        definition.outgoing.setdefault(src, []).append(Edge(src, tgt, e.get("condition")))
    if not definition.start and definition.nodes:
        definition.start = next(iter(definition.nodes))
    return definition


def eval_condition(expr: str | None, context: dict[str, Any]) -> bool:
    if not expr:
        return True
    expr = expr.strip()
    if "==" in expr:
        left, right = [p.strip().strip("'\"") for p in expr.split("==", 1)]
        return str(context.get(left, context.get(left.lower(), ""))) == right
    if "!=" in expr:
        left, right = [p.strip().strip("'\"") for p in expr.split("!=", 1)]
        return str(context.get(left, "")) != right
    if "=" in expr:
        left, right = [p.strip().strip("'\"") for p in expr.split("=", 1)]
        return str(context.get(left, context.get(left.lower(), ""))) == right
    if expr.lower() in ("true", "1", "yes"):
        return True
    if expr.lower() in ("false", "0", "no"):
        return False
    return str(context.get(expr, "")) not in ("", "None", "false", "0")


def next_nodes(definition: ProcessDef, current: str, context: dict[str, Any]) -> list[str]:
    node = definition.nodes.get(current)
    edges = definition.outgoing.get(current) or []
    if not node:
        return []
    if node.type == "exclusiveGateway":
        for e in edges:
            if eval_condition(e.condition, context):
                return [e.target]
        return [edges[-1].target] if edges else []
    if node.type == "parallelGateway":
        return [e.target for e in edges]
    return [e.target for e in edges if eval_condition(e.condition, context)] or ([edges[0].target] if edges else [])


def _text(el) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip()
