"""Stylised cartoon materials for EEVEE (run inside Blender)."""
from __future__ import annotations

import bpy


def srgb_to_linear(color) -> tuple:
    """Design colours are authored in sRGB (like a colour picker); shaders need linear."""
    out = []
    for c in color[:3]:
        c = max(0.0, float(c))
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def _principled(mat: bpy.types.Material):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def material(name: str, color, roughness: float = 0.55, metallic: float = 0.0, specular: float = 0.35,
             emission: float = 0.0, alpha: float = 1.0, coat: float = 0.0,
             subsurface: float = 0.0) -> bpy.types.Material:
    """Get or create a Principled material with a flat cartoon colour."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = _principled(mat)
    rgba = (*srgb_to_linear(color), 1.0)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Specular IOR Level"].default_value = specular
    if coat:
        bsdf.inputs["Coat Weight"].default_value = coat
    if subsurface:
        bsdf.inputs["Subsurface Weight"].default_value = subsurface
        bsdf.inputs["Subsurface Radius"].default_value = (0.4, 0.15, 0.08)
        bsdf.inputs["Subsurface Scale"].default_value = 0.02
    if emission:
        bsdf.inputs["Emission Color"].default_value = rgba
        bsdf.inputs["Emission Strength"].default_value = emission
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        mat.surface_render_method = "BLENDED"
    mat.diffuse_color = rgba
    return mat


def outline_material(name: str = "toon_outline", color=(0.03, 0.025, 0.03)) -> bpy.types.Material:
    """Inverted-hull outline: emissive dark colour, back faces culled."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1.0)
    em.inputs["Strength"].default_value = 1.0
    links.new(em.outputs[0], out.inputs[0])
    mat.use_backface_culling = True
    mat.diffuse_color = (*color, 1.0)
    return mat


def glow_material(name: str, color, strength: float = 4.0, alpha: float = 0.35) -> bpy.types.Material:
    """Transparent emissive material for energy shields and power effects."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*srgb_to_linear(color), 1.0)
    em.inputs["Strength"].default_value = strength
    tr = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    lw = nodes.new("ShaderNodeLayerWeight")  # fresnel rim: edges glow more than the centre
    lw.inputs["Blend"].default_value = 0.35
    ramp = nodes.new("ShaderNodeMath")
    ramp.operation = "MULTIPLY_ADD"
    ramp.inputs[1].default_value = 1.0 - alpha
    ramp.inputs[2].default_value = alpha
    links.new(lw.outputs["Facing"], ramp.inputs[0])
    links.new(ramp.outputs[0], mix.inputs[0])
    links.new(tr.outputs[0], mix.inputs[1])
    links.new(em.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])
    mat.surface_render_method = "BLENDED"
    mat.use_backface_culling = False
    mat.diffuse_color = (*color, alpha)
    return mat


def gradient_sky_material(name: str, horizon, zenith, strength: float = 1.0) -> bpy.types.Material:
    """Emissive vertical gradient for the inside of a sky dome."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = strength
    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    cr = nodes.new("ShaderNodeValToRGB")
    cr.color_ramp.elements[0].position = 0.5
    cr.color_ramp.elements[0].color = (*srgb_to_linear(horizon), 1.0)
    cr.color_ramp.elements[1].position = 0.85
    cr.color_ramp.elements[1].color = (*srgb_to_linear(zenith), 1.0)
    links.new(tc.outputs["Generated"], sep.inputs[0])
    links.new(sep.outputs["Z"], cr.inputs[0])
    links.new(cr.outputs["Color"], em.inputs["Color"])
    links.new(em.outputs[0], out.inputs[0])
    return mat


def embroidered_material(name: str, base, thread, scale: float = 38.0) -> bpy.types.Material:
    """Fabric with a procedural embroidery pattern (Voronoi motifs + woven stripes)."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _principled(mat)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = scale
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = scale * 0.5
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.04
    ramp.color_ramp.elements[0].color = (*srgb_to_linear(thread), 1)
    ramp.color_ramp.elements[1].position = 0.09
    ramp.color_ramp.elements[1].color = (*srgb_to_linear(base), 1)
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["Factor"].default_value = 0.15
    nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    nt.links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["A"])
    nt.links.new(wave.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.55
    bsdf.inputs["Sheen Weight"].default_value = 0.4
    mat.diffuse_color = (*srgb_to_linear(base), 1)
    return mat
