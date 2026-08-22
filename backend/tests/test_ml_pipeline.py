"""ML pipeline tests: training, model history, explainability, and report generation."""

import io
import pytest


SALES_CSV = (
    b"date,region,product,units,price,revenue,cost,profit\n"
    b"2024-01-01,North,Electronics,10,100,1000,600,400\n"
    b"2024-01-02,South,Software,20,50,1000,300,700\n"
    b"2024-01-03,East,Electronics,15,100,1500,900,600\n"
    b"2024-01-04,West,Software,25,50,1250,375,875\n"
    b"2024-01-05,North,Services,5,200,1000,500,500\n"
    b"2024-01-06,South,Electronics,12,100,1200,720,480\n"
    b"2024-01-07,East,Services,8,200,1600,800,800\n"
    b"2024-01-08,West,Electronics,18,100,1800,1080,720\n"
    b"2024-01-09,North,Software,30,50,1500,450,1050\n"
    b"2024-01-10,South,Services,6,200,1200,600,600\n"
    b"2024-01-11,East,Electronics,22,100,2200,1320,880\n"
    b"2024-01-12,West,Software,35,50,1750,525,1225\n"
    b"2024-01-13,North,Electronics,14,100,1400,840,560\n"
    b"2024-01-14,South,Services,9,200,1800,900,900\n"
    b"2024-01-15,East,Software,28,50,1400,420,980\n"
    b"2024-01-16,West,Electronics,16,100,1600,960,640\n"
    b"2024-01-17,North,Services,7,200,1400,700,700\n"
    b"2024-01-18,South,Electronics,20,100,2000,1200,800\n"
    b"2024-01-19,East,Software,32,50,1600,480,1120\n"
    b"2024-01-20,West,Services,10,200,2000,1000,1000\n"
)


@pytest.fixture
def setup(client):
    client.post(
        "/auth/register",
        json={
            "email": "ml@example.com",
            "password": "StrongPass1!",
            "full_name": "ML User",
        },
    )
    r = client.post(
        "/auth/login", json={"email": "ml@example.com", "password": "StrongPass1!"}
    )
    tokens = r.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    upload = client.post(
        "/datasets/upload",
        headers=headers,
        files={"file": ("sales.csv", io.BytesIO(SALES_CSV), "text/csv")},
    )
    dataset_id = upload.json()["id"]
    return headers, dataset_id


def test_training_options_returns_columns(client, setup):
    headers, dataset_id = setup
    r = client.get(f"/datasets/{dataset_id}/train/options", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "columns" in body
    assert "target_candidates" in body
    assert body["row_count"] == 20


def test_train_produces_model_run(client, setup):
    headers, dataset_id = setup
    r = client.post(
        f"/datasets/{dataset_id}/train",
        headers=headers,
        json={
            "target_column": "revenue",
            "task_type": "regression",
            "enable_tuning": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "best_model" in body or "best_model_name" in body or "leaderboard" in body


def test_model_history_tracks_versions(client, setup):
    headers, dataset_id = setup
    client.post(
        f"/datasets/{dataset_id}/train",
        headers=headers,
        json={
            "target_column": "revenue",
            "task_type": "regression",
            "enable_tuning": False,
        },
    )

    r = client.get(f"/datasets/{dataset_id}/model/history", headers=headers)
    assert r.status_code == 200
    history = r.json()
    assert len(history) >= 1


def test_explainability_after_training(client, setup):
    headers, dataset_id = setup
    client.post(
        f"/datasets/{dataset_id}/train",
        headers=headers,
        json={
            "target_column": "revenue",
            "task_type": "regression",
            "enable_tuning": False,
        },
    )

    r = client.get(f"/datasets/{dataset_id}/explain", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "features" in body or "importance" in body or "method" in body


def test_profiling_returns_quality_scores(client, setup):
    headers, dataset_id = setup
    r = client.get(f"/datasets/{dataset_id}/quality", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "quality" in body
    assert "overall_score" in body["quality"]


def test_cleaning_plan_and_preview(client, setup):
    headers, dataset_id = setup

    r = client.get(f"/datasets/{dataset_id}/clean/plan", headers=headers)
    assert r.status_code == 200

    r2 = client.post(f"/datasets/{dataset_id}/clean/preview", headers=headers, json={})
    assert r2.status_code == 200


def test_cleaning_apply_and_revert(client, setup):
    headers, dataset_id = setup

    r = client.post(f"/datasets/{dataset_id}/clean/apply", headers=headers, json={})
    assert r.status_code == 200

    detail = client.get(f"/datasets/{dataset_id}", headers=headers)
    assert detail.json()["has_cleaned_version"] is True

    r2 = client.post(f"/datasets/{dataset_id}/clean/revert", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["reverted"] is True


def test_analytics_dashboard(client, setup):
    headers, dataset_id = setup
    r = client.get(f"/datasets/{dataset_id}/dashboard", headers=headers)
    assert r.status_code == 200


def test_analytics_query(client, setup):
    headers, dataset_id = setup
    r = client.post(
        f"/datasets/{dataset_id}/analytics/query",
        headers=headers,
        json={
            "measure": "revenue",
            "aggregation": "sum",
            "dimension": "region",
            "chart_type": "bar",
        },
    )
    assert r.status_code == 200


def test_dashboard_layout_crud(client, setup):
    headers, dataset_id = setup

    r = client.post(
        f"/datasets/{dataset_id}/dashboard-layouts",
        headers=headers,
        json={
            "name": "My Dashboard",
            "charts": [{"type": "bar", "measure": "revenue"}],
            "is_default": True,
        },
    )
    assert r.status_code == 201
    layout_id = r.json()["id"]

    r2 = client.get(f"/datasets/{dataset_id}/dashboard-layouts", headers=headers)
    assert len(r2.json()) == 1

    r3 = client.put(
        f"/datasets/{dataset_id}/dashboard-layouts/{layout_id}",
        headers=headers,
        json={
            "name": "Updated Dashboard",
            "charts": [{"type": "line", "measure": "profit"}],
            "is_default": True,
        },
    )
    assert r3.status_code == 200
    assert r3.json()["name"] == "Updated Dashboard"

    r4 = client.delete(
        f"/datasets/{dataset_id}/dashboard-layouts/{layout_id}", headers=headers
    )
    assert r4.status_code == 200


def test_report_generation(client, setup):
    headers, dataset_id = setup
    r = client.get(f"/datasets/{dataset_id}/report", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_export_csv(client, setup):
    headers, dataset_id = setup
    r = client.get(f"/datasets/{dataset_id}/export", headers=headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
