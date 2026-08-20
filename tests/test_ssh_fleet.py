from pathlib import Path

from nexus_v3.ssh_fleet import BEGIN_MARKER, END_MARKER, render_authorized_keys, write_authorized_keys


def test_render_preserves_unmanaged_keys_and_replaces_managed_block():
    existing = "\n".join(
        [
            "ssh-ed25519 AAAAold personal-key",
            BEGIN_MARKER,
            "ssh-ed25519 AAAAstale nexus-device=stale",
            END_MARKER,
            "",
        ]
    )
    fleet = "\n".join(
        [
            "ssh-ed25519 AAAAone nexus-device=one",
            "ssh-ed25519 AAAAtwo nexus-device=two",
        ]
    )

    rendered, count = render_authorized_keys(existing, fleet)

    assert count == 2
    assert "AAAAold" in rendered
    assert "AAAAstale" not in rendered
    assert rendered.count(BEGIN_MARKER) == 1
    assert rendered.count(END_MARKER) == 1
    assert "AAAAone" in rendered
    assert "AAAAtwo" in rendered


def test_duplicate_fleet_keys_are_deduplicated():
    fleet = "\n".join(
        [
            "ssh-ed25519 AAAAsame nexus-device=one",
            "ssh-ed25519 AAAAsame nexus-device=duplicate",
        ]
    )

    rendered, count = render_authorized_keys("", fleet)

    assert count == 1
    assert rendered.count("AAAAsame") == 1


def test_write_is_idempotent(tmp_path: Path):
    target = tmp_path / ".ssh" / "authorized_keys"
    fleet = "ssh-ed25519 AAAAone nexus-device=one\n"

    changed, count = write_authorized_keys(target, fleet)
    assert changed is True
    assert count == 1

    changed, count = write_authorized_keys(target, fleet)
    assert changed is False
    assert count == 1
