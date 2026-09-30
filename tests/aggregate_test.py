from __future__ import annotations

from datetime import date, datetime, timezone

from pipeline.transform import DailyCount, Post, aggregate, extract

DAY = date(2026, 9, 1)


def make(post_id: str, text: str, repost_of: str | None = None) -> Post:
	return Post(post_id, "x", "@a", datetime(2026, 9, 1, 10, tzinfo=timezone.utc),
				text, repost_of)


def test_extract_normalises_hashtags_and_domains():
	found = extract("Lisez #Vaccins et #vaccins https://WWW.Actu.example/a?b=1 !")
	assert found.hashtags == {"vaccins"}
	assert found.domains == {"actu.example"}


def test_url_fragment_is_not_a_hashtag():
	found = extract("Voir https://site.example/page#section #climat")
	assert found.hashtags == {"climat"}
	assert found.domains == {"site.example"}


def test_trailing_punctuation_is_not_part_of_the_domain():
	assert extract("Source : https://site.example.").domains == {"site.example"}


def test_text_without_hashtag_or_link():
	found = extract("@compte_1 tu as vu ?")
	assert found.hashtags == frozenset() and found.domains == frozenset()


def test_aggregate_counts_posts_and_originals():
	posts = [
		make("1", "#climat https://a.example/x"),
		make("2", "#climat https://a.example/x", repost_of="1"),  # repartage
		make("3", "#climat #climat #energie"),                    # hashtag répété : compte une fois
	]
	assert aggregate(posts, "x", DAY) == [
		DailyCount(DAY, "x", "domain", "a.example", posts=2, originals=1),
		DailyCount(DAY, "x", "hashtag", "climat", posts=3, originals=2),
		DailyCount(DAY, "x", "hashtag", "energie", posts=1, originals=1),
	]