import json
import unittest

import support
from mcp_fixer import patch_format, patch_gen

MESSY = json.loads((support.TESTS / "fixtures" / "messy_tools.json").read_text(encoding="utf-8"))
CLEAN = json.loads((support.TESTS / "fixtures" / "clean_tools.json").read_text(encoding="utf-8"))["tools"]


def sentence(n):
    return f"Sentence number {n} says something useful here."


class TrimTests(unittest.TestCase):
    def test_short_text_is_only_whitespace_collapsed(self):
        self.assertEqual(patch_gen.trim_description("  a   b \n c  "), "a b c")

    def test_whole_sentences_are_kept_while_they_fit(self):
        text = " ".join(sentence(i) for i in range(30))  # about 1,500 characters
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("here."))
        self.assertTrue(text.startswith(trimmed))
        self.assertGreater(len(trimmed), 400)

    def test_exactly_the_limit_is_untouched(self):
        for size in (499, 500):
            with self.subTest(size):
                text = "x" * size
                self.assertEqual(patch_gen.trim_description(text), text)

    def test_one_over_the_limit_is_cut(self):
        text = ("word " * 200).strip()  # 999 characters, no sentence end
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("…"))
        trimmed = patch_gen.trim_description("y" * 501)
        self.assertEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("…"))

    def test_a_first_sentence_over_the_limit_is_cut_at_a_word_boundary(self):
        text = "alpha " * 120 + "end. Second sentence."
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("alpha…"))

    def test_question_and_exclamation_marks_end_sentences(self):
        text = ("Is this a question? " + "Yes it is! " + sentence(1) + " ") * 20
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed[-1] in ".!?")

    def test_the_result_is_never_longer_than_the_limit(self):
        for size in range(480, 560):
            with self.subTest(size):
                text = ("ab " * size)[:size]
                self.assertLessEqual(len(patch_gen.trim_description(text)), 500)


class GenerateTests(unittest.TestCase):
    def test_the_messy_fixture_gives_the_expected_patch(self):
        patch = patch_gen.generate_patch(MESSY)
        self.assertEqual(patch["patchVersion"], 1)
        self.assertEqual(list(patch["tools"]), ["run", "searchItems"])  # list_items has no finding
        run = patch["tools"]["run"]
        self.assertEqual(run["base"], patch_format.fingerprint(MESSY[0]))
        self.assertEqual(run["params"], {"order": {"enum": ["asc", "desc"]}})
        self.assertEqual(
            run["review"],
            ["parameter 'order': enum inferred from its description (2 values); check the list is complete"],
        )
        todo = {(t["rule"], t.get("param")) for t in run["todo"]}
        self.assertEqual(todo, {("D002", None), ("N001", None), ("P001", "q"), ("P002", "q"), ("P005", None)})
        self.assertTrue(all(t["hint"] for t in run["todo"]))
        self.assertEqual(
            run["context"],
            {"description": "Runs it", "params": {"order": "Sort order, one of: asc, desc", "q": ""}},
        )
        search = patch["tools"]["searchItems"]
        self.assertEqual([t["rule"] for t in search["todo"]], ["D001"])
        self.assertNotIn("rename", run)
        self.assertNotIn("description", run)
        self.assertEqual(patch["notes"], ["tool names mix naming styles"])

    def test_the_output_always_validates(self):
        for tools in (MESSY, CLEAN, [], ["oops", {"name": ""}, None]):
            with self.subTest(len(tools)):
                patch_format.validate_patch(patch_gen.generate_patch(tools))

    def test_a_clean_server_gives_an_empty_patch(self):
        self.assertEqual(patch_gen.generate_patch(CLEAN), {"patchVersion": 1, "tools": {}})

    def test_a_long_description_is_trimmed_with_a_review_note(self):
        long_text = " ".join(sentence(i) for i in range(30))
        tool = {
            "name": "get_item",
            "description": long_text,
            "inputSchema": {
                "type": "object",
                "properties": {"item_id": {"type": "string", "description": "Identifier"}},
                "required": ["item_id"],
            },
        }
        entry = patch_gen.generate_patch([tool])["tools"]["get_item"]
        self.assertLessEqual(len(entry["description"]), 500)
        self.assertEqual(len(entry["review"]), 1)
        self.assertRegex(entry["review"][0], r"^description trimmed from \d+ to \d+ characters$")
        self.assertNotIn("todo", entry)

    def test_malformed_entries_become_notes(self):
        patch = patch_gen.generate_patch(["oops"] + CLEAN)
        self.assertEqual(patch["tools"], {})
        self.assertEqual(patch["notes"], ["tool entry 0 is malformed"])

    def test_duplicate_names_get_one_entry_and_a_note(self):
        tool = {"name": "dup_tool", "description": "", "inputSchema": {"type": "object", "properties": {}}}
        patch = patch_gen.generate_patch([tool, dict(tool)])
        self.assertEqual(list(patch["tools"]), ["dup_tool"])
        self.assertIn("duplicate tool names cannot be patched separately: dup_tool", patch["notes"])

    def test_a_duplicate_description_todo_names_the_other_tool(self):
        a = {"name": "alpha_tool", "description": "Search the catalog for products.", "inputSchema": {"type": "object", "properties": {}}}
        b = dict(a, name="beta_tool")
        patch = patch_gen.generate_patch([a, b])
        hint = patch["tools"]["alpha_tool"]["todo"][0]["hint"]
        self.assertIn("beta_tool", hint)

    def test_source_is_recorded_for_a_stdio_server_only(self):
        stdio = {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "s", "serverVersion": "1"}
        self.assertEqual(patch_gen.generate_patch([], stdio)["source"], {"serverName": "s", "serverVersion": "1"})
        self.assertNotIn("source", patch_gen.generate_patch([]))

    def test_the_output_is_deterministic(self):
        first = patch_gen.render_patch(patch_gen.generate_patch(MESSY))
        second = patch_gen.render_patch(patch_gen.generate_patch(MESSY))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("}\n"))

    def test_the_input_tools_are_not_modified(self):
        before = json.dumps(MESSY, sort_keys=True)
        patch_gen.generate_patch(MESSY)
        self.assertEqual(json.dumps(MESSY, sort_keys=True), before)

    def test_non_ascii_text_is_written_readably(self):
        tool = {"name": "recuperer", "description": "", "inputSchema": {"type": "object", "properties": {}}, "title": "日本語"}
        text = patch_gen.render_patch(patch_gen.generate_patch([tool]))
        self.assertNotIn("\\u", text)


if __name__ == "__main__":
    unittest.main()
