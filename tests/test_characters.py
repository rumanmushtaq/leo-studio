"""Character registry and consistency."""
from core.character_manager import CharacterRegistry, slugify


def test_aliases(registry):
    assert registry.resolve_id("Ustad Akram") == "ustad_akram"
    assert registry.resolve_id("لیو") == "leo"
    assert registry.resolve_id("Bully") == "boss"


def test_same_design_every_time(tmp_path):
    a = CharacterRegistry(registry_file=tmp_path / "a.json").get_or_create("Zara", "a girl at school")
    b = CharacterRegistry(registry_file=tmp_path / "b.json").get_or_create("Zara", "a girl at school")
    assert a.data == b.data and a.design_hash() == b.design_hash()
    assert a.data["gender"] == "female" and a.data["procedural"]


def test_leo_preset_matches_spec(registry):
    leo = registry.get_or_create("Leo").data
    assert leo["hair"]["color"][0] > leo["hair"]["color"][2]          # brown hair
    assert leo["eye_color"][2] > 0.8                                   # blue eyes
    assert {"cape", "emblem_L", "agent_badge"} <= set(leo["accessories"])
    assert leo["costume"]["shoe_style"] == "boots"


def test_registry_persists_and_reuses_assets(tmp_path):
    reg = CharacterRegistry(registry_file=tmp_path / "r.json")
    spec = reg.get_or_create("leo")
    h = spec.design_hash()
    reg.mark_built("leo")
    assert spec.design_hash() == h            # build metadata does not change the design hash
    reg.save()
    again = CharacterRegistry(registry_file=tmp_path / "r.json")
    assert again.characters["leo"].data["asset_hash"] == h


def test_mentions_with_groups(registry):
    for c in ("boss", "chintu", "motu"):
        registry.get_or_create(c)
    assert set(registry.mentions("The bullies walk in")) == {"boss", "chintu", "motu"}
    assert registry.mentions("Boss points at Karim")[0] == "boss"


def test_slugify_urdu():
    assert slugify("استاد اکرم").isascii()
