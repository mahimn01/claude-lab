import unittest

from tpl import TemplateError, render


class Basics(unittest.TestCase):
    def test_variables(self):
        self.assertEqual(render("Hi {{ name }}!", {"name": "Ada"}), "Hi Ada!")
        self.assertEqual(render("{{ user.city }}", {"user": {"city": "Oslo"}}), "Oslo")
        self.assertEqual(render("[{{ nope }}]", {}), "[]")

    def test_filters_and_escaping(self):
        self.assertEqual(render("{{ name|upper }}", {"name": "ada"}), "ADA")
        self.assertEqual(render("{{ x }}", {"x": "<b>"}), "&lt;b&gt;")
        self.assertEqual(render("{{ x|safe }}", {"x": "<b>"}), "<b>")

    def test_if_and_for(self):
        self.assertEqual(render("{% if a %}yes{% else %}no{% endif %}", {"a": 1}), "yes")
        self.assertEqual(render("{% for i in xs %}{{ i }},{% endfor %}", {"xs": [1, 2]}), "1,2,")

    def test_errors(self):
        with self.assertRaises(TemplateError):
            render("{% if a %}x", {})


if __name__ == "__main__":
    unittest.main()
