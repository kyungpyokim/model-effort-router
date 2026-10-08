import unittest

from model_effort_router.events import iter_events


class EventsTests(unittest.TestCase):
    def test_skips_invalid_json_and_non_objects_preserving_order(self):
        text = 'bad\n\n[]\nnull\n42\ntrue\n"text"\n{"type":"a"}\n{"type":"b"}'
        self.assertEqual(list(iter_events(text)), [{"type": "a"}, {"type": "b"}])

    def test_preserves_empty_and_nested_objects(self):
        self.assertEqual(list(iter_events('{}\n{"item":{"text":"hello"}}\n')), [{}, {"item": {"text": "hello"}}])

    def test_empty_stream(self):
        self.assertEqual(list(iter_events("")), [])

    def test_existing_private_parser_names_share_the_iterator(self):
        from evaluation import usage
        from model_effort_router.host import codex_exec

        self.assertIs(usage._events, iter_events)
        self.assertIs(codex_exec._events, iter_events)
