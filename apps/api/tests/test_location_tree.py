import pytest


@pytest.mark.integration
def test_complete_farm_tree_via_api(client, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm

    create_resp = client.post(
        f"/farms/{farm.id}/locations",
        headers=headers,
        json={
            "location_type_code": "greenhouse",
            "code": "gh-1",
            "name": "Greenhouse",
            "greenhouse_classification": "nursery",
        },
    )
    assert create_resp.status_code == 201
    greenhouse_id = create_resp.json()["id"]

    for code, name, location_type_code in (
        ("section-b", "Germination Chamber B", "germination_chamber"),
        ("section-a", "Seeding Station A", "seeding_station"),
    ):
        resp = client.post(
            f"/farms/{farm.id}/locations",
            headers=headers,
            json={
                "location_type_code": location_type_code,
                "code": code,
                "name": name,
                "parent_location_id": greenhouse_id,
            },
        )
        assert resp.status_code == 201

    tree_resp = client.get(f"/farms/{farm.id}/locations/tree", headers=headers)
    assert tree_resp.status_code == 200
    tree = tree_resp.json()

    assert len(tree) == 1
    root = tree[0]
    assert root["code"] == "GH-1"
    assert len(root["children"]) == 2
    # Deterministic ordering by normalized code: SECTION-A before SECTION-B.
    assert [child["code"] for child in root["children"]] == ["SECTION-A", "SECTION-B"]


@pytest.mark.integration
def test_complete_derived_path(client, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    greenhouse_id = client.post(
        f"/farms/{farm.id}/locations",
        headers=headers,
        json={"location_type_code": "greenhouse", "code": "gh-1", "name": "Greenhouse", "greenhouse_classification": "nursery"},
    ).json()["id"]
    chamber_id = client.post(
        f"/farms/{farm.id}/locations",
        headers=headers,
        json={"location_type_code": "germination_chamber", "code": "GC-01", "name": "Chamber", "parent_location_id": greenhouse_id},
    ).json()["id"]

    path_resp = client.get(f"/farms/{farm.id}/locations/{chamber_id}/path", headers=headers)
    assert path_resp.status_code == 200
    body = path_resp.json()
    assert [entry["code"] for entry in body["path"]] == ["GH-1", "GC-01"]
    assert body["path_string"] == "GH-1 / GC-01"
