import json
from datetime import date

from pipeline.transform import clean

DAY = date(2026, 9, 1)


def post(**overrides) -> str:
    base = {"post_id": "x_1", "platform": "x", "author": "@a",
            "created_at": "2026-09-01T10:00:00Z", "text": "bonjour #test", "repost_of": None}
    base.update(overrides)
    return json.dumps(base)


def test_valid_post_is_kept():
    posts, stats = clean([post()], "x", DAY)
    assert len(posts) == 1
    assert posts[0].created_at.hour == 10
    assert stats["lignes_gardees"] == 1


def test_each_rule_rejects_once():
    lines = [
        post(post_id="ok"),
        '{"post_id": "tronque", "text": "ligne coup',     # JSON invalide
        json.dumps({"post_id": "x_2", "platform": "x"}),   # champ manquant
        post(post_id="x_3", text="   "),                   # texte vide
        post(post_id="x_4", created_at="14/09/2026 08h32"),  # date illisible
        post(post_id="x_5", created_at="2020-01-01T00:00:00Z"),  # hors de la journée
        post(post_id="x_6", platform="facebook"),          # mauvaise plateforme
        post(post_id="ok"),                                # doublon
    ]
    posts, stats = clean(lines, "x", DAY)
    assert [p.post_id for p in posts] == ["ok"]
    assert stats == {"lignes_lues": 8, "json_invalide": 1, "champ_manquant": 1,
                     "texte_vide": 1, "date_illisible": 1, "hors_de_la_journee": 1,
                     "mauvaise_plateforme": 1, "doublon": 1, "lignes_gardees": 1}


def test_timezone_is_converted_to_utc():
    # 01:30 à Paris (UTC+2) le 2 septembre = 23:30 UTC le 1er : appartient au 1er.
    posts, _ = clean([post(created_at="2026-09-02T01:30:00+02:00")], "x", DAY)
    assert len(posts) == 1


def test_date_without_timezone_is_rejected():
    _, stats = clean([post(created_at="2026-09-01T10:00:00")], "x", DAY)
    assert stats["date_illisible"] == 1


def test_blank_lines_are_ignored():
    _, stats = clean([post(), "", "\n"], "x", DAY)
    assert stats["lignes_lues"] == 1