bl_info = {
    "name": "ChatGPT Blender Bridge (Local MCP)",
    "author": "OpenAI-assisted community implementation",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > ChatGPT",
    "description": "Localhost MCP bridge for scene inspection, modeling, materials, animation, validation and rendering",
    "category": "Interface",
}

import bpy
import bmesh
import json
import math
import os
import queue
import socket
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from mathutils import Euler

ADDON_ID = __package__ or __name__
DEFAULT_PORT = 9877
MAX_LINE_BYTES = 2_000_000
MAX_PENDING = 12
APPROVAL_TIMEOUT_SECONDS = 170
REQUEST_TIMEOUT_SECONDS = 180

_REQUEST_QUEUE = queue.Queue(maxsize=100)
_PENDING = []                 # Accessed on Blender's main thread only.
_SERVER_THREAD = None
_SERVER_SOCKET = None
_SERVER_STOP = threading.Event()
_SERVER_ERROR = ""
_SERVER_PORT = DEFAULT_PORT
_TIMER_REGISTERED = False

APPROVAL_REQUIRED_TOOLS = {
    "delete_object",
    "execute_python",
    "save_blend_copy",
    "render_preview",
}

TOOLS = [
    {
        "name": "get_status",
        "description": "Returns bridge status, Blender version, active file and security settings.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "scene_overview",
        "description": "Summarizes the current scene, objects, frame, render settings and active object.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_objects",
        "description": "Lists objects in the current scene with transforms, mesh counts and assigned materials.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Optional Blender object type filter, e.g. MESH or CAMERA."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_object",
        "description": "Returns details about one named object, including dimensions, mesh statistics, modifiers, materials and animation state.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False,
        },
    },
    {
        "name": "create_primitive",
        "description": "Creates a mesh primitive. Supported kinds: CUBE, SPHERE, CYLINDER, CONE, PLANE, TORUS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["CUBE", "SPHERE", "CYLINDER", "CONE", "PLANE", "TORUS"]},
                "name": {"type": "string"},
                "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "size": {"type": "number", "exclusiveMinimum": 0, "default": 2.0},
            },
            "required": ["kind"], "additionalProperties": False,
        },
    },
    {
        "name": "create_camera",
        "description": "Adds a camera at the supplied world-space location and Euler rotation in degrees.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "make_active": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "create_light",
        "description": "Adds a light. Supported kinds: POINT, SUN, SPOT, AREA.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["POINT", "SUN", "SPOT", "AREA"]},
                "name": {"type": "string"},
                "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "power": {"type": "number", "exclusiveMinimum": 0, "default": 1000},
                "color": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 3, "maxItems": 3},
            },
            "required": ["kind"], "additionalProperties": False,
        },
    },
    {
        "name": "set_transform",
        "description": "Changes the location, Euler rotation (degrees), and/or scale of a named object. Omitted fields are left unchanged.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "scale": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            },
            "required": ["name"], "additionalProperties": False,
        },
    },
    {
        "name": "duplicate_object",
        "description": "Duplicates an object and its data, optionally assigning a new name and offsetting its location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "new_name": {"type": "string"},
                "offset": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            },
            "required": ["name"], "additionalProperties": False,
        },
    },
    {
        "name": "delete_object",
        "description": "Deletes a named object. Blender shows a local approval prompt before this change is applied.",
        "inputSchema": {
            "type": "object", "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False,
        },
    },
    {
        "name": "create_material",
        "description": "Creates or updates a material with an RGBA base color, metallic value and roughness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "color": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4},
                "metallic": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.0},
                "roughness": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
            },
            "required": ["name"], "additionalProperties": False,
        },
    },
    {
        "name": "assign_material",
        "description": "Assigns a named material to a named object, replacing the first material slot when present.",
        "inputSchema": {
            "type": "object",
            "properties": {"object_name": {"type": "string"}, "material_name": {"type": "string"}},
            "required": ["object_name", "material_name"], "additionalProperties": False,
        },
    },
    {
        "name": "set_frame",
        "description": "Sets the current scene frame.",
        "inputSchema": {
            "type": "object", "properties": {"frame": {"type": "integer", "minimum": 0}},
            "required": ["frame"], "additionalProperties": False,
        },
    },
    {
        "name": "keyframe_transform",
        "description": "Sets and keyframes the provided transform channels for an object at a specified frame.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}, "frame": {"type": "integer", "minimum": 0},
                "location": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "scale": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            },
            "required": ["name", "frame"], "additionalProperties": False,
        },
    },
    {
        "name": "validate_scene",
        "description": "Runs a non-destructive scene sanity check and reports missing camera, empty meshes, non-manifold mesh edges and material issues.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "repair_scene",
        "description": "Applies selected non-destructive repairs: recalculate mesh normals, assign a default material to material-less meshes, ensure material nodes exist, and set the first available camera if none is active.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fixes": {"type": "array", "items": {"type": "string", "enum": ["recalculate_normals", "assign_default_material", "enable_material_nodes", "set_first_camera"]}, "minItems": 1},
            },
            "required": ["fixes"], "additionalProperties": False,
        },
    },
    {
        "name": "render_preview",
        "description": "Renders a PNG preview to the configured project folder. Requires local approval first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Optional PNG filename, saved inside the configured project folder."},
                "resolution_x": {"type": "integer", "minimum": 64, "maximum": 1920, "default": 1280},
                "resolution_y": {"type": "integer", "minimum": 64, "maximum": 1080, "default": 720},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "save_blend_copy",
        "description": "Saves a copy of the current .blend project in the configured project folder without changing the currently open file. Requires local approval and does not overwrite existing files.",
        "inputSchema": {
            "type": "object", "properties": {"filename": {"type": "string", "description": "Optional .blend filename, saved inside the configured project folder."}},
            "additionalProperties": False,
        },
    },
    {
        "name": "execute_python",
        "description": "Executes a Python script inside Blender with bpy available. Disabled by default; enable it in add-on preferences and approve each execution in Blender. This is full code execution, not a sandbox.",
        "inputSchema": {
            "type": "object", "properties": {"code": {"type": "string", "maxLength": 20000}},
            "required": ["code"], "additionalProperties": False,
        },
    },
]

TOOL_MAP = {tool["name"]: tool for tool in TOOLS}


class BridgeRequest:
    def __init__(self, tool, arguments):
        self.request_id = uuid.uuid4().hex[:12]
        self.tool = tool
        self.arguments = arguments or {}
        self.created = time.monotonic()
        self.state = "queued"
        self.decision = None
        self.event = threading.Event()
        self.response = None


def _addon_preferences():
    entry = bpy.context.preferences.addons.get(ADDON_ID)
    return entry.preferences if entry else None


def _write_audit(event, req=None, details=None):
    """Append a full JSONL audit event. Called only from Blender's main thread."""
    prefs = _addon_preferences()
    if prefs and not prefs.audit_log_enabled:
        return
    try:
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": str(event),
            "request_id": req.request_id if req else None,
            "tool": req.tool if req else None,
            "arguments": req.arguments if req else None,
            "details": details,
        }
        path = _project_root() / "chatgpt_blender_bridge_audit.jsonl"
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
    except Exception as exc:
        print(f"[ChatGPT Blender Bridge] Audit-Log konnte nicht geschrieben werden: {exc}")


def _project_root():
    prefs = _addon_preferences()
    raw = (prefs.project_root if prefs else "").strip()
    if raw:
        path = Path(os.path.expandvars(os.path.expanduser(bpy.path.abspath(raw)))).resolve()
    elif bpy.data.filepath:
        path = Path(bpy.data.filepath).resolve().parent
    else:
        path = Path.home() / "BlenderChatGPTProjects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_project_file(filename, default_name):
    root = _project_root().resolve()
    candidate_name = (filename or default_name).strip()
    if not candidate_name:
        candidate_name = default_name
    candidate = Path(os.path.expanduser(candidate_name))
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("Dateipfad außerhalb des konfigurierten Projektordners ist gesperrt.")
    if target.exists():
        raise FileExistsError(f"Datei existiert bereits; Überschreiben ist gesperrt: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _get_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Objekt nicht gefunden: {name}")
    return obj


def _vec3(value, default):
    if value is None:
        return tuple(default)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Erwartet wird ein Array mit genau drei Zahlen.")
    return tuple(float(x) for x in value)


def _transform_summary(obj):
    return {
        "name": obj.name,
        "type": obj.type,
        "location": [round(float(x), 5) for x in obj.location],
        "rotation_deg": [round(math.degrees(float(x)), 4) for x in obj.rotation_euler],
        "scale": [round(float(x), 5) for x in obj.scale],
        "dimensions": [round(float(x), 5) for x in obj.dimensions],
        "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
        "has_animation": bool(obj.animation_data and obj.animation_data.action),
    }


def _ensure_shader_nodes(material):
    """Ensure a material has a Principled BSDF connected to Material Output."""
    changed = False
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        changed = True
    output = next((node for node in nodes if node.type == "OUTPUT_MATERIAL"), None)
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        changed = True
    bsdf_socket = bsdf.outputs.get("BSDF")
    surface_socket = output.inputs.get("Surface")
    if bsdf_socket and surface_socket and not any(link.from_node == bsdf and link.to_node == output and link.to_socket == surface_socket for link in links):
        links.new(bsdf_socket, surface_socket)
        changed = True
    return bsdf, changed


def _scene_overview():
    scene = bpy.context.scene
    counts = {}
    for obj in scene.objects:
        counts[obj.type] = counts.get(obj.type, 0) + 1
    return {
        "scene": scene.name,
        "file": bpy.data.filepath or None,
        "is_saved": bool(bpy.data.filepath),
        "blender_version": bpy.app.version_string,
        "object_count": len(scene.objects),
        "object_counts_by_type": counts,
        "active_object": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None,
        "selected_objects": [obj.name for obj in bpy.context.selected_objects],
        "frame": scene.frame_current,
        "frame_range": [scene.frame_start, scene.frame_end],
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage],
        "camera": scene.camera.name if scene.camera else None,
        "materials": [mat.name for mat in bpy.data.materials],
    }


def _inspect_object(name):
    obj = _get_object(name)
    result = _transform_summary(obj)
    result.update({
        "data_name": obj.data.name if obj.data else None,
        "modifiers": [{"name": mod.name, "type": mod.type, "show_viewport": mod.show_viewport, "show_render": mod.show_render} for mod in obj.modifiers],
        "collections": [collection.name for collection in obj.users_collection],
        "constraints": [{"name": con.name, "type": con.type, "mute": con.mute} for con in obj.constraints],
        "custom_properties": [key for key in obj.keys() if key != "_RNA_UI"],
    })
    if obj.type == "MESH" and obj.data:
        result["mesh"] = {
            "vertices": len(obj.data.vertices),
            "edges": len(obj.data.edges),
            "polygons": len(obj.data.polygons),
            "uv_layers": [layer.name for layer in obj.data.uv_layers],
        }
    return result


def _set_transform(obj, args):
    if "location" in args:
        obj.location = _vec3(args["location"], obj.location)
    if "rotation_deg" in args:
        rot = _vec3(args["rotation_deg"], tuple(math.degrees(float(x)) for x in obj.rotation_euler))
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = tuple(math.radians(float(x)) for x in rot)
    if "scale" in args:
        obj.scale = _vec3(args["scale"], obj.scale)
    return _transform_summary(obj)


def _apply_tool(tool, args):
    if tool == "get_status":
        prefs = _addon_preferences()
        return {
            "status": "running" if _SERVER_THREAD and _SERVER_THREAD.is_alive() and not _SERVER_ERROR else "error" if _SERVER_ERROR else "starting",
            "host": "127.0.0.1", "port": _SERVER_PORT,
            "server_error": _SERVER_ERROR or None,
            "blender_version": bpy.app.version_string,
            "addon_version": "1.0.0",
            "python_execution_enabled": bool(prefs and prefs.allow_python_execution),
            "approval_required_for_critical_actions": bool(prefs.require_approval if prefs else True),
            "project_root": str(_project_root()),
        }

    if tool == "scene_overview":
        return _scene_overview()

    if tool == "list_objects":
        type_filter = (args.get("type") or "").upper().strip()
        limit = max(1, min(int(args.get("limit", 100)), 500))
        objects = []
        for obj in bpy.context.scene.objects:
            if type_filter and obj.type != type_filter:
                continue
            item = _transform_summary(obj)
            if obj.type == "MESH" and obj.data:
                item["mesh"] = {"vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons)}
            objects.append(item)
            if len(objects) >= limit:
                break
        return {"count_returned": len(objects), "limit": limit, "objects": objects}

    if tool == "inspect_object":
        return _inspect_object(str(args["name"]))

    if tool == "create_primitive":
        kind = str(args.get("kind", "CUBE")).upper()
        size = float(args.get("size", 2.0))
        if not math.isfinite(size) or size <= 0 or size > 100000:
            raise ValueError("size muss größer als 0 und höchstens 100000 sein.")
        location = _vec3(args.get("location"), (0, 0, 0))
        operators = {
            "CUBE": bpy.ops.mesh.primitive_cube_add,
            "SPHERE": bpy.ops.mesh.primitive_uv_sphere_add,
            "CYLINDER": bpy.ops.mesh.primitive_cylinder_add,
            "CONE": bpy.ops.mesh.primitive_cone_add,
            "PLANE": bpy.ops.mesh.primitive_plane_add,
            "TORUS": bpy.ops.mesh.primitive_torus_add,
        }
        if kind not in operators:
            raise ValueError(f"Unbekannter Primitive-Typ: {kind}")
        if kind == "PLANE":
            operators[kind](size=size, location=location)
        elif kind == "TORUS":
            operators[kind](location=location, major_radius=size * 0.5, minor_radius=size * 0.125)
        elif kind == "CUBE":
            operators[kind](size=size, location=location)
        elif kind == "SPHERE":
            operators[kind](radius=size * 0.5, location=location)
        else:
            operators[kind](location=location, radius=size * 0.5)
        obj = bpy.context.object
        if args.get("name"):
            obj.name = str(args["name"])[:120]
        return {"created": _transform_summary(obj)}

    if tool == "create_camera":
        name = str(args.get("name", "ChatGPT_Camera"))[:120]
        location = _vec3(args.get("location"), (7, -7, 5))
        rotation = _vec3(args.get("rotation_deg"), (63, 0, 45))
        cam_data = bpy.data.cameras.new(name=f"{name}_Data")
        obj = bpy.data.objects.new(name, cam_data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = location
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = tuple(math.radians(v) for v in rotation)
        if bool(args.get("make_active", True)):
            bpy.context.scene.camera = obj
        return {"created": _transform_summary(obj), "active_scene_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None}

    if tool == "create_light":
        kind = str(args.get("kind", "AREA")).upper()
        if kind not in {"POINT", "SUN", "SPOT", "AREA"}:
            raise ValueError(f"Unbekannter Licht-Typ: {kind}")
        name = str(args.get("name", f"ChatGPT_{kind.title()}"))[:120]
        data = bpy.data.lights.new(name=f"{name}_Data", type=kind)
        data.energy = float(args.get("power", 1000.0))
        color = args.get("color", [1.0, 1.0, 1.0])
        if len(color) != 3 or any(float(v) < 0 or float(v) > 1 for v in color):
            raise ValueError("color muss drei Zahlen zwischen 0 und 1 enthalten.")
        data.color = tuple(float(v) for v in color)
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = _vec3(args.get("location"), (4, -4, 5))
        rotation = _vec3(args.get("rotation_deg"), (0, 0, 0))
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = tuple(math.radians(v) for v in rotation)
        return {"created": _transform_summary(obj), "light_type": kind, "power": data.energy}

    if tool == "set_transform":
        return {"updated": _set_transform(_get_object(str(args["name"])), args)}

    if tool == "duplicate_object":
        source = _get_object(str(args["name"]))
        copy_obj = source.copy()
        if source.data:
            copy_obj.data = source.data.copy()
        bpy.context.scene.collection.objects.link(copy_obj)
        if args.get("new_name"):
            copy_obj.name = str(args["new_name"])[:120]
        offset = _vec3(args.get("offset"), (1.0, 0.0, 0.0))
        copy_obj.location = tuple(copy_obj.location[i] + offset[i] for i in range(3))
        return {"duplicated_from": source.name, "created": _transform_summary(copy_obj)}

    if tool == "delete_object":
        obj = _get_object(str(args["name"]))
        name = obj.name
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"deleted": name}

    if tool == "create_material":
        name = str(args["name"])[:120]
        color = args.get("color", [0.8, 0.8, 0.8, 1.0])
        if len(color) != 4 or any(float(v) < 0 or float(v) > 1 for v in color):
            raise ValueError("color muss vier RGBA-Zahlen zwischen 0 und 1 enthalten.")
        metallic = float(args.get("metallic", 0.0))
        roughness = float(args.get("roughness", 0.5))
        if not 0 <= metallic <= 1 or not 0 <= roughness <= 1:
            raise ValueError("metallic und roughness müssen zwischen 0 und 1 liegen.")
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
        mat.diffuse_color = tuple(float(v) for v in color)
        bsdf, _nodes_changed = _ensure_shader_nodes(mat)
        base = bsdf.inputs.get("Base Color")
        metal = bsdf.inputs.get("Metallic")
        rough = bsdf.inputs.get("Roughness")
        if base: base.default_value = tuple(float(v) for v in color)
        if metal: metal.default_value = metallic
        if rough: rough.default_value = roughness
        return {"material": mat.name, "color": list(mat.diffuse_color), "metallic": metallic, "roughness": roughness}

    if tool == "assign_material":
        obj = _get_object(str(args["object_name"]))
        mat = bpy.data.materials.get(str(args["material_name"]))
        if mat is None:
            raise ValueError(f"Material nicht gefunden: {args['material_name']}")
        if not obj.data or not hasattr(obj.data, "materials"):
            raise ValueError(f"Objekt '{obj.name}' unterstützt keine Material-Slots.")
        if len(obj.data.materials) > 0:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        return {"object": obj.name, "material": mat.name, "slots": [slot.material.name if slot.material else None for slot in obj.material_slots]}

    if tool == "set_frame":
        frame = int(args["frame"])
        if frame < 0:
            raise ValueError("frame muss mindestens 0 sein.")
        bpy.context.scene.frame_set(frame)
        return {"frame": bpy.context.scene.frame_current}

    if tool == "keyframe_transform":
        obj = _get_object(str(args["name"]))
        frame = int(args["frame"])
        if frame < 0:
            raise ValueError("frame muss mindestens 0 sein.")
        scene = bpy.context.scene
        scene.frame_set(frame)
        channels = []
        if "location" in args:
            obj.location = _vec3(args["location"], obj.location)
            obj.keyframe_insert(data_path="location", frame=frame)
            channels.append("location")
        if "rotation_deg" in args:
            rot = _vec3(args["rotation_deg"], tuple(math.degrees(float(x)) for x in obj.rotation_euler))
            obj.rotation_mode = "XYZ"
            obj.rotation_euler = tuple(math.radians(v) for v in rot)
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)
            channels.append("rotation_euler")
        if "scale" in args:
            obj.scale = _vec3(args["scale"], obj.scale)
            obj.keyframe_insert(data_path="scale", frame=frame)
            channels.append("scale")
        if not channels:
            raise ValueError("Mindestens location, rotation_deg oder scale angeben.")
        return {"object": obj.name, "frame": frame, "keyframed_channels": channels}

    if tool == "validate_scene":
        scene = bpy.context.scene
        errors, warnings, info = [], [], []
        if scene.camera is None:
            warnings.append("Keine aktive Kamera in der Szene.")
        if not scene.objects:
            warnings.append("Die Szene enthält keine Objekte.")
        for obj in scene.objects:
            if obj.type == "MESH" and obj.data:
                if len(obj.data.vertices) == 0 or len(obj.data.polygons) == 0:
                    warnings.append(f"Mesh '{obj.name}' hat keine Vertices oder Flächen.")
                if len(obj.data.materials) == 0:
                    info.append(f"Mesh '{obj.name}' hat kein Material zugewiesen.")
                if len(obj.data.polygons) > 0 and len(obj.data.polygons) < 100000:
                    bm = bmesh.new()
                    try:
                        bm.from_mesh(obj.data)
                        non_manifold = sum(1 for edge in bm.edges if not edge.is_manifold)
                        if non_manifold:
                            warnings.append(f"Mesh '{obj.name}' hat {non_manifold} nicht-manifold Kanten (lokaler Mesh-Test).")
                    finally:
                        bm.free()
            if obj.name not in bpy.data.objects:
                errors.append(f"Objektreferenz ungültig: {obj.name}")
        if not bpy.data.filepath:
            info.append("Projekt ist noch nicht als .blend-Datei gespeichert.")
        return {"valid": not errors and not warnings, "errors": errors, "warnings": warnings, "info": info}

    if tool == "repair_scene":
        fixes = args.get("fixes", [])
        if not isinstance(fixes, list) or not fixes:
            raise ValueError("fixes muss eine nicht-leere Liste sein.")
        allowed = {"recalculate_normals", "assign_default_material", "enable_material_nodes", "set_first_camera"}
        unknown = sorted(set(fixes) - allowed)
        if unknown:
            raise ValueError(f"Unbekannte Reparaturschritte: {unknown}")
        report = []
        scene = bpy.context.scene
        if "recalculate_normals" in fixes:
            for obj in scene.objects:
                if obj.type != "MESH" or not obj.data or not obj.data.polygons:
                    continue
                bm = bmesh.new()
                try:
                    bm.from_mesh(obj.data)
                    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                    bm.to_mesh(obj.data)
                    obj.data.update()
                    report.append({"fix": "recalculate_normals", "object": obj.name, "status": "repaired"})
                finally:
                    bm.free()
        if "assign_default_material" in fixes:
            mat = bpy.data.materials.get("ChatGPT_Default_Material")
            if mat is None:
                mat = bpy.data.materials.new("ChatGPT_Default_Material")
                mat.diffuse_color = (0.65, 0.65, 0.65, 1.0)
            for obj in scene.objects:
                if obj.type == "MESH" and obj.data and hasattr(obj.data, "materials") and not any(existing is not None for existing in obj.data.materials):
                    if len(obj.data.materials) > 0:
                        obj.data.materials[0] = mat
                    else:
                        obj.data.materials.append(mat)
                    report.append({"fix": "assign_default_material", "object": obj.name, "status": "repaired"})
        if "enable_material_nodes" in fixes:
            for mat in bpy.data.materials:
                _bsdf, changed = _ensure_shader_nodes(mat)
                if changed:
                    report.append({"fix": "enable_material_nodes", "material": mat.name, "status": "shader_nodes_repaired"})
        if "set_first_camera" in fixes and scene.camera is None:
            camera = next((obj for obj in scene.objects if obj.type == "CAMERA"), None)
            if camera:
                scene.camera = camera
                report.append({"fix": "set_first_camera", "object": camera.name, "status": "repaired"})
            else:
                report.append({"fix": "set_first_camera", "status": "skipped_no_camera_found"})
        return {"applied_fixes": report, "count": len(report), "note": "Nur die in fixes genannten, nicht-destruktiven Reparaturen wurden ausgeführt."}

    if tool == "render_preview":
        scene = bpy.context.scene
        filename = args.get("filename") or f"chatgpt_preview_{time.strftime('%Y%m%d_%H%M%S')}.png"
        filename = Path(str(filename)).name
        if not filename.lower().endswith(".png"):
            filename += ".png"
        target = _safe_project_file(filename, f"chatgpt_preview_{time.strftime('%Y%m%d_%H%M%S')}.png")
        rx = int(args.get("resolution_x", 1280))
        ry = int(args.get("resolution_y", 720))
        if not 64 <= rx <= 1920 or not 64 <= ry <= 1080:
            raise ValueError("Renderauflösung ist auf höchstens 1920 × 1080 begrenzt.")
        render = scene.render
        old = {
            "filepath": render.filepath,
            "file_format": render.image_settings.file_format,
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "resolution_percentage": render.resolution_percentage,
        }
        try:
            render.filepath = str(target.with_suffix(""))
            render.image_settings.file_format = "PNG"
            render.resolution_x = rx
            render.resolution_y = ry
            render.resolution_percentage = 100
            bpy.ops.render.render(write_still=True)
        finally:
            render.filepath = old["filepath"]
            render.image_settings.file_format = old["file_format"]
            render.resolution_x = old["resolution_x"]
            render.resolution_y = old["resolution_y"]
            render.resolution_percentage = old["resolution_percentage"]
        return {"rendered": str(target), "resolution": [rx, ry], "engine": scene.render.engine, "exists": target.exists()}

    if tool == "save_blend_copy":
        if not bpy.data.filepath:
            raise ValueError("Bitte speichere die .blend-Datei zuerst einmal manuell, bevor eine Kopie erstellt wird.")
        filename = args.get("filename") or f"{Path(bpy.data.filepath).stem}_chatgpt_copy_{time.strftime('%Y%m%d_%H%M%S')}.blend"
        filename = Path(str(filename)).name
        if not filename.lower().endswith(".blend"):
            filename += ".blend"
        target = _safe_project_file(filename, f"project_copy_{time.strftime('%Y%m%d_%H%M%S')}.blend")
        result = bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True)
        return {"saved_copy": str(target), "operator_result": sorted(result), "current_open_file_unchanged": True, "exists": target.exists()}

    if tool == "execute_python":
        prefs = _addon_preferences()
        if not prefs or not prefs.allow_python_execution:
            raise PermissionError("Python-Ausführung ist standardmäßig gesperrt. Aktivieren Sie sie in den Add-on-Präferenzen und starten Sie den Aufruf erneut.")
        code = args.get("code", "")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code darf nicht leer sein.")
        if len(code) > 20000:
            raise ValueError("Python-Code darf höchstens 20000 Zeichen lang sein.")
        env = {"bpy": bpy, "math": math, "Euler": Euler, "scene": bpy.context.scene, "results": {}}
        exec(compile(code, "<ChatGPT Blender Bridge>", "exec"), env, env)
        payload = env.get("results", {})
        try:
            normalized = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            normalized = str(payload)
        return {"executed": True, "results": normalized, "note": "Skript lief mit den vollständigen Rechten des Blender-Prozesses; es gibt keine Python-Sandbox."}

    raise ValueError(f"Unbekanntes Tool: {tool}")


def _complete(req, response):
    req.response = response
    req.state = "done"
    req.event.set()


def _process_tool_request(req):
    try:
        result = _apply_tool(req.tool, req.arguments)
        _write_audit("completed", req, {"ok": True, "result": result})
        _complete(req, {"ok": True, "result": result})
    except Exception as exc:
        failure = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=5),
        }
        _write_audit("failed", req, failure)
        _complete(req, failure)


def _requires_approval(req, prefs):
    return bool(prefs and prefs.require_approval and req.tool in APPROVAL_REQUIRED_TOOLS)


def _main_thread_timer():
    global _TIMER_REGISTERED
    prefs = _addon_preferences()

    # Process newly queued requests in Blender's main thread only.
    for _ in range(20):
        try:
            req = _REQUEST_QUEUE.get_nowait()
        except queue.Empty:
            break
        if req.event.is_set():
            continue
        if req.tool == "execute_python" and (not prefs or not prefs.allow_python_execution):
            failure = {"ok": False, "error": "Python-Ausführung ist deaktiviert. Erst in den Add-on-Präferenzen aktivieren."}
            _write_audit("denied", req, failure)
            _complete(req, failure)
            continue
        _write_audit("request_received", req, {"requires_approval": _requires_approval(req, prefs)})
        if _requires_approval(req, prefs):
            if len(_PENDING) >= MAX_PENDING:
                _complete(req, {"ok": False, "error": "Zu viele ausstehende Freigaben. Bitte zuerst die Warteschlange in Blender leeren."})
                continue
            req.state = "pending"
            _PENDING.append(req)
            _write_audit("approval_requested", req, {"expires_in_seconds": APPROVAL_TIMEOUT_SECONDS})
        else:
            _process_tool_request(req)

    # Process decisions made using the Blender sidebar.
    for req in list(_PENDING):
        if req.event.is_set() or (time.monotonic() - req.created > APPROVAL_TIMEOUT_SECONDS):
            if not req.event.is_set():
                failure = {"ok": False, "error": "Freigabe abgelaufen; Aktion wurde nicht ausgeführt."}
                _write_audit("approval_expired", req, failure)
                _complete(req, failure)
            _PENDING.remove(req)
            continue
        if req.decision is True:
            _PENDING.remove(req)
            _write_audit("approved", req, {"approved_in_blender": True})
            _process_tool_request(req)
        elif req.decision is False:
            _PENDING.remove(req)
            _write_audit("rejected", req, {"approved_in_blender": False})
            failure = {"ok": False, "error": "Aktion vom Benutzer in Blender abgelehnt."}
            _write_audit("failed", req, failure)
            _complete(req, failure)

    return 0.1


def _connection_handler(conn):
    try:
        conn.settimeout(REQUEST_TIMEOUT_SECONDS + 10)
        reader = conn.makefile("rb")
        writer = conn.makefile("wb")
        while not _SERVER_STOP.is_set():
            raw = reader.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_LINE_BYTES:
                writer.write((json.dumps({"ok": False, "error": "Request zu groß."}) + "\n").encode("utf-8"))
                writer.flush()
                break
            try:
                payload = json.loads(raw.decode("utf-8"))
                tool = str(payload.get("tool", ""))
                arguments = payload.get("arguments") or {}
                if tool not in TOOL_MAP:
                    response = {"ok": False, "error": f"Unbekanntes Tool: {tool}"}
                elif not isinstance(arguments, dict):
                    response = {"ok": False, "error": "arguments muss ein Objekt sein."}
                else:
                    req = BridgeRequest(tool, arguments)
                    try:
                        _REQUEST_QUEUE.put(req, timeout=2.0)
                    except queue.Full:
                        response = {"ok": False, "error": "Blender-Request-Warteschlange ist ausgelastet."}
                    else:
                        if req.event.wait(REQUEST_TIMEOUT_SECONDS):
                            response = req.response or {"ok": False, "error": "Leere Antwort von Blender."}
                        else:
                            response = {"ok": False, "error": "Zeitüberschreitung beim Warten auf Blender. Bei kritischen Aktionen prüfen Sie die Freigabe-Leiste in der Blender-Seitenleiste."}
                wire = json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
                writer.write(wire.encode("utf-8"))
                writer.flush()
            except Exception as exc:
                try:
                    writer.write((json.dumps({"ok": False, "error": f"Request-Fehler: {type(exc).__name__}: {exc}"}) + "\n").encode("utf-8"))
                    writer.flush()
                except Exception:
                    break
    except Exception:
        pass
    finally:
        try: conn.close()
        except Exception: pass


def _server_loop():
    global _SERVER_SOCKET, _SERVER_ERROR
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", _SERVER_PORT))
        server.listen(8)
        server.settimeout(0.5)
        _SERVER_SOCKET = server
        _SERVER_ERROR = ""
        while not _SERVER_STOP.is_set():
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            worker = threading.Thread(target=_connection_handler, args=(conn,), daemon=True)
            worker.start()
        try: server.close()
        except Exception: pass
    except Exception as exc:
        _SERVER_ERROR = f"{type(exc).__name__}: {exc}"
    finally:
        _SERVER_SOCKET = None


def _start_server():
    global _SERVER_THREAD, _SERVER_PORT, _SERVER_ERROR
    prefs = _addon_preferences()
    _SERVER_PORT = int(prefs.port if prefs else DEFAULT_PORT)
    _SERVER_STOP.clear()
    if _SERVER_THREAD and _SERVER_THREAD.is_alive():
        return
    _SERVER_THREAD = threading.Thread(target=_server_loop, name="ChatGPTBlenderBridge", daemon=True)
    _SERVER_THREAD.start()


def _stop_server():
    _SERVER_STOP.set()
    # Release client threads waiting for requests that have not reached the UI timer.
    while True:
        try:
            queued = _REQUEST_QUEUE.get_nowait()
        except queue.Empty:
            break
        if not queued.event.is_set():
            _complete(queued, {"ok": False, "error": "Add-on wurde deaktiviert; Aktion abgebrochen."})
    sock = _SERVER_SOCKET
    if sock:
        try: sock.shutdown(socket.SHUT_RDWR)
        except Exception: pass
        try: sock.close()
        except Exception: pass
    thread = _SERVER_THREAD
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    for req in list(_PENDING):
        _complete(req, {"ok": False, "error": "Add-on wurde deaktiviert; Aktion abgebrochen."})
    _PENDING.clear()


class CHATGPTBRIDGE_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    port: bpy.props.IntProperty(name="Lokaler Port", default=DEFAULT_PORT, min=1024, max=65535, description="Nur an 127.0.0.1 gebunden; nach einer Portänderung Add-on neu aktivieren")
    require_approval: bpy.props.BoolProperty(name="Freigabe für kritische Aktionen", default=True, description="Vor Löschen, Rendern, Speichern einer Kopie und Python-Ausführung in Blender genehmigen")
    allow_python_execution: bpy.props.BoolProperty(name="Python-Skripte zulassen", default=False, description="Erlaubt beliebigen Python-Code im Blender-Prozess; nur bei vertrauenswürdigen MCP-Clients aktivieren")
    audit_log_enabled: bpy.props.BoolProperty(name="Vollständiges Audit-Log aktivieren", default=True, description="Protokolliert Anfragen, Parameter, Freigaben, Ergebnisse und Fehler als JSONL im Projektordner")
    project_root: bpy.props.StringProperty(name="Projektordner", default="", subtype="DIR_PATH", description="Dateien werden nur in diesem Ordner gespeichert. Leer = aktueller .blend-Ordner oder ~/BlenderChatGPTProjects")

    def draw(self, context):
        layout = self.layout
        layout.label(text="Lokale Verbindung: 127.0.0.1 (keine LAN-/Internet-Freigabe)", icon="LOCKED")
        layout.prop(self, "port")
        layout.prop(self, "require_approval")
        layout.prop(self, "allow_python_execution")
        layout.prop(self, "audit_log_enabled")
        layout.prop(self, "project_root")
        col = layout.column(align=True)
        col.label(text="Python-Ausführung hat die Rechte des Blender-Prozesses.", icon="ERROR")
        col.label(text="Sie ist kein Sandbox-Modus und bleibt standardmäßig deaktiviert.")
        col.label(text="Portänderungen werden nach Deaktivieren/Aktivieren wirksam.")


class CHATGPTBRIDGE_OT_decide(bpy.types.Operator):
    bl_idname = "chatgpt_bridge.decide"
    bl_label = "Freigabe entscheiden"
    bl_description = "Genehmigt oder verwirft die angeforderte Aktion"

    request_id: bpy.props.StringProperty()
    approve: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        for req in _PENDING:
            if req.request_id == self.request_id and req.state == "pending":
                req.decision = self.approve
                self.report({"INFO"}, "Aktion genehmigt." if self.approve else "Aktion abgelehnt.")
                return {"FINISHED"}
        self.report({"WARNING"}, "Die Anforderung ist nicht mehr verfügbar.")
        return {"CANCELLED"}


class CHATGPTBRIDGE_OT_restart(bpy.types.Operator):
    bl_idname = "chatgpt_bridge.restart"
    bl_label = "Bridge neu starten"
    bl_description = "Startet den lokalen MCP-Bridge-Port neu"

    def execute(self, context):
        _stop_server()
        _start_server()
        self.report({"INFO"}, f"Bridge wird auf 127.0.0.1:{_SERVER_PORT} gestartet.")
        return {"FINISHED"}


class CHATGPTBRIDGE_PT_panel(bpy.types.Panel):
    bl_label = "ChatGPT Blender Bridge"
    bl_idname = "CHATGPTBRIDGE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ChatGPT"

    def draw(self, context):
        layout = self.layout
        prefs = _addon_preferences()
        online = bool(_SERVER_THREAD and _SERVER_THREAD.is_alive() and not _SERVER_ERROR)
        box = layout.box()
        box.label(text="MCP-Bridge: " + ("läuft" if online else "nicht verfügbar"), icon="CHECKMARK" if online else "ERROR")
        box.label(text=f"127.0.0.1:{_SERVER_PORT}")
        if _SERVER_ERROR:
            box.label(text=_SERVER_ERROR[:120], icon="ERROR")
        row = box.row()
        row.operator("chatgpt_bridge.restart", icon="FILE_REFRESH")
        if prefs:
            box.label(text="Python: " + ("AN" if prefs.allow_python_execution else "AUS"), icon="SCRIPT")
            box.label(text="Kritische Freigaben: " + ("AN" if prefs.require_approval else "AUS"), icon="LOCKED")
            box.label(text=f"Projektordner: {_project_root()}")
            box.label(text="Audit-Log: " + ("AN" if prefs.audit_log_enabled else "AUS"))
        layout.separator()
        layout.label(text=f"Wartende Freigaben ({len(_PENDING)})", icon="QUESTION")
        if not _PENDING:
            layout.label(text="Keine offenen Anfragen.")
        for req in list(_PENDING):
            box = layout.box()
            box.label(text=f"{req.tool} · {req.request_id}", icon="ERROR")
            summary = json.dumps(req.arguments, ensure_ascii=False, default=str)
            box.label(text=(summary[:110] + "…") if len(summary) > 110 else summary)
            row = box.row(align=True)
            approve = row.operator("chatgpt_bridge.decide", text="Genehmigen", icon="CHECKMARK")
            approve.request_id = req.request_id
            approve.approve = True
            reject = row.operator("chatgpt_bridge.decide", text="Ablehnen", icon="CANCEL")
            reject.request_id = req.request_id
            reject.approve = False
        layout.separator()
        layout.label(text="Änderungen per Strg+Z rückgängig machen, sofern Blender dies unterstützt.")


_CLASSES = (
    CHATGPTBRIDGE_Preferences,
    CHATGPTBRIDGE_OT_decide,
    CHATGPTBRIDGE_OT_restart,
    CHATGPTBRIDGE_PT_panel,
)


def register():
    global _TIMER_REGISTERED
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if not _TIMER_REGISTERED:
        bpy.app.timers.register(_main_thread_timer, first_interval=0.2, persistent=True)
        _TIMER_REGISTERED = True
    _start_server()


def unregister():
    global _TIMER_REGISTERED
    _stop_server()
    try:
        if bpy.app.timers.is_registered(_main_thread_timer):
            bpy.app.timers.unregister(_main_thread_timer)
    except Exception:
        pass
    _TIMER_REGISTERED = False
    for cls in reversed(_CLASSES):
        try: bpy.utils.unregister_class(cls)
        except Exception: pass


if __name__ == "__main__":
    register()
