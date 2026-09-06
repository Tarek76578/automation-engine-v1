from app.integrations.meta_messenger import parse_page_messenger_events, stable_event_id


def test_parse_page_messenger_text_event():
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "PAGE123",
                "messaging": [
                    {
                        "sender": {"id": "USER456"},
                        "recipient": {"id": "PAGE123"},
                        "timestamp": 1700000000000,
                        "message": {"mid": "m_abc", "text": "هل المنتج متوفر؟"},
                    }
                ],
            }
        ],
    }
    events = parse_page_messenger_events(payload)
    assert len(events) == 1
    assert events[0]["page_id"] == "PAGE123"
    assert events[0]["sender_id"] == "USER456"
    assert events[0]["message"] == "هل المنتج متوفر؟"
    assert events[0]["event_id"] == "m_abc"


def test_parser_ignores_non_text_events():
    payload = {"object": "page", "entry": [{"id": "PAGE123", "messaging": [{"sender": {"id": "USER456"}, "message": {"attachments": []}}]}]}
    assert parse_page_messenger_events(payload) == []


def test_stable_event_id_is_deterministic():
    event = {"sender_id": "USER456", "timestamp": 123, "message": "hello"}
    assert stable_event_id("PAGE123", event) == stable_event_id("PAGE123", event)
    assert stable_event_id("PAGE123", event).startswith("meta:")
