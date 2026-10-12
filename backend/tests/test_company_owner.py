"""Each company belongs to the lead generator who found it first: a salesperson sees, searches and opens only their
own; managers see everyone's, filter by owner and reassign."""

from app.models.enums import UserRole

API = "/companies"


def test_salespeople_see_only_their_own_companies(client_for):
    alice, a = client_for(UserRole.SALES_AGENT)
    bob, b = client_for(UserRole.SALES_AGENT)
    boss, _ = client_for(UserRole.SALES_MANAGER)
    mine = alice.post(API, json={"name": "Alpha Owned Trading"}).json()
    assert mine["owner_user_id"] == a.id  # the creator owns it
    theirs = bob.post(API, json={"name": "Beta Owned Trading"}).json()

    assert [c["name"] for c in alice.get(API).json()["items"]] == ["Alpha Owned Trading"]
    assert alice.get(f"{API}/{theirs['id']}").status_code == 404
    assert alice.patch(f"{API}/{theirs['id']}", json={"name": "x"}).status_code == 404
    assert alice.get(f"{API}/{theirs['id']}/people").status_code == 404
    assert [h["name"] for h in alice.get(f"{API}/search", params={"q": "Owned Trading"}).json()] == \
        ["Alpha Owned Trading"]

    assert {c["name"] for c in boss.get(API).json()["items"]} == {"Alpha Owned Trading", "Beta Owned Trading"}
    assert [c["name"] for c in boss.get(API, params={"owner_id": b.id}).json()["items"]] == ["Beta Owned Trading"]
    assert alice.patch(f"{API}/{mine['id']}/owner", json={"owner_user_id": b.id}).status_code == 403
    assert boss.patch(f"{API}/{theirs['id']}/owner", json={"owner_user_id": a.id}).json()["owner_user_id"] == a.id
    assert alice.get(f"{API}/{theirs['id']}").status_code == 200
    assert bob.get(f"{API}/{theirs['id']}").status_code == 404
