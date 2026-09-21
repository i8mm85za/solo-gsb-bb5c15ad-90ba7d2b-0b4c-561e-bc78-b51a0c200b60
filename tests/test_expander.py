"""Engine tests using only the standard library (run: python3 -m unittest)."""
import unittest

from app.expander import (
    ExpansionError,
    MeasureData,
    build_structure,
    expand,
    expand_structure,
    validate,
)


def M(number, markers=(), ending_numbers=None, repeat_times=None):
    return MeasureData(
        number=number,
        markers=frozenset(markers),
        ending_numbers=tuple(ending_numbers) if ending_numbers else None,
        repeat_times=repeat_times,
    )


def seq(measures, max_steps=1000):
    steps, _ = expand(measures, max_steps)
    return [s.measure for s in steps]


class TestPairedRepeats(unittest.TestCase):
    def test_simple_repeat(self):
        measures = [M(1), M(2, ["repeat_begin"]), M(3, ["repeat_end"]), M(4)]
        self.assertEqual(seq(measures), [1, 2, 3, 2, 3, 4])

    def test_repeat_times(self):
        measures = [M(1), M(2, ["repeat_begin"]), M(3, ["repeat_end"], repeat_times=3), M(4)]
        self.assertEqual(seq(measures), [1, 2, 3, 2, 3, 2, 3, 4])

    def test_implicit_repeat_from_start(self):
        measures = [M(1), M(2, ["repeat_end"]), M(3)]
        self.assertEqual(seq(measures), [1, 2, 1, 2, 3])
        _, warnings = expand(measures)
        self.assertIn("IMPLICIT_REPEAT_FROM_START", {w.code for w in warnings})

    def test_nested_repeats(self):
        # outer 1..5, inner 2..3, each played twice
        measures = [
            M(1, ["repeat_begin"]),
            M(2, ["repeat_begin"]),
            M(3, ["repeat_end"]),
            M(4),
            M(5, ["repeat_end"]),
        ]
        self.assertEqual(seq(measures), [1, 2, 3, 2, 3, 4, 5, 1, 2, 3, 2, 3, 4, 5])

    def test_unclosed_repeat_is_error_with_measure(self):
        measures = [M(1), M(2, ["repeat_begin"]), M(3)]
        errors, _ = validate(measures)
        self.assertEqual([e.code for e in errors], ["UNCLOSED_REPEAT"])
        self.assertEqual(errors[0].measure, 2)
        with self.assertRaises(ExpansionError):
            expand(measures)


class TestEndings(unittest.TestCase):
    def measures_ab(self):
        return [
            M(1),
            M(2, ["repeat_begin"]),
            M(3),
            M(4, ["ending_begin"], ending_numbers=[1]),
            M(5, ["ending_end", "repeat_end"]),
            M(6, ["ending_begin"], ending_numbers=[2]),
            M(7, ["ending_end"]),
        ]

    def test_first_second_ending(self):
        self.assertEqual(seq(self.measures_ab()), [1, 2, 3, 4, 5, 2, 3, 6, 7])

    def test_three_endings_each_with_repeat_barline(self):
        measures = [
            M(1),
            M(2, ["repeat_begin"]),
            M(3),
            M(4, ["ending_begin"], ending_numbers=[1]),
            M(5, ["ending_end", "repeat_end"]),
            M(6, ["ending_begin"], ending_numbers=[2]),
            M(7, ["ending_end", "repeat_end"], repeat_times=3),
            M(8, ["ending_begin"], ending_numbers=[3]),
            M(9, ["ending_end"]),
        ]
        self.assertEqual(seq(measures), [1, 2, 3, 4, 5, 2, 3, 6, 7, 2, 3, 8, 9])

    def test_shared_ending_numbers(self):
        # endings "1,2." and "3." over a 3x repeat
        measures = [
            M(1, ["repeat_begin"]),
            M(2, ["ending_begin"], ending_numbers=[1, 2]),
            M(3, ["ending_end", "repeat_end"], repeat_times=3),
            M(4, ["ending_begin"], ending_numbers=[3]),
            M(5, ["ending_end"]),
        ]
        self.assertEqual(seq(measures), [1, 2, 3, 1, 2, 3, 1, 4, 5])

    def test_unclosed_ending(self):
        measures = [
            M(1, ["repeat_begin"]),
            M(2, ["ending_begin"], ending_numbers=[1]),
            M(3, ["repeat_end"]),
        ]
        errors, _ = validate(measures)
        self.assertIn("UNCLOSED_ENDING", {e.code for e in errors})
        self.assertEqual(next(e for e in errors if e.code == "UNCLOSED_ENDING").measure, 2)

    def test_ending_without_repeat(self):
        measures = [
            M(1, ["ending_begin"], ending_numbers=[1]),
            M(2, ["ending_end"]),
        ]
        errors, _ = validate(measures)
        self.assertIn("ENDING_WITHOUT_REPEAT", {e.code for e in errors})

    def test_missing_ending_numbers(self):
        measures = [
            M(1, ["repeat_begin"]),
            M(2, ["ending_begin"]),
            M(3, ["ending_end", "repeat_end"]),
        ]
        errors, _ = validate(measures)
        self.assertIn("ENDING_NUMBERS_MISSING", {e.code for e in errors})


class TestJumps(unittest.TestCase):
    def test_dc_al_fine(self):
        measures = [M(1), M(2), M(3, ["fine"]), M(4), M(5, ["dc_al_fine"])]
        self.assertEqual(seq(measures), [1, 2, 3, 4, 5, 1, 2, 3])

    def test_ds_al_fine(self):
        measures = [
            M(1),
            M(2, ["segno"]),
            M(3),
            M(4, ["fine"]),
            M(5),
            M(6, ["ds_al_fine"]),
        ]
        self.assertEqual(seq(measures), [1, 2, 3, 4, 5, 6, 2, 3, 4])

    def test_dc_al_coda(self):
        measures = [
            M(1),
            M(2),
            M(3, ["to_coda"]),
            M(4),
            M(5, ["dc_al_coda"]),
            M(6, ["coda_sign"]),
            M(7),
        ]
        self.assertEqual(seq(measures), [1, 2, 3, 4, 5, 1, 2, 3, 6, 7])

    def test_ds_al_coda(self):
        measures = [
            M(1),
            M(2, ["segno"]),
            M(3),
            M(4, ["to_coda"]),
            M(5),
            M(6, ["ds_al_coda"]),
            M(7, ["coda_sign"]),
            M(8),
        ]
        self.assertEqual(seq(measures), [1, 2, 3, 4, 5, 6, 2, 3, 4, 7, 8])

    def test_repeats_ignored_after_jump(self):
        measures = [
            M(1, ["repeat_begin"]),
            M(2, ["repeat_end"]),
            M(3, ["fine"]),
            M(4, ["dc_al_fine"]),
        ]
        # repeat taken once, then straight through after D.C.
        self.assertEqual(seq(measures), [1, 2, 1, 2, 3, 4, 1, 2, 3])

    def test_second_ending_taken_after_dc(self):
        measures = [
            M(1, ["repeat_begin"]),
            M(2, ["ending_begin"], ending_numbers=[1]),
            M(3, ["ending_end", "repeat_end"]),
            M(4, ["ending_begin"], ending_numbers=[2]),
            M(5, ["ending_end"]),
            M(6, ["fine"]),
            M(7, ["dc_al_fine"]),
        ]
        # after D.C. the pass counter selects the 2nd ending
        self.assertEqual(seq(measures), [1, 2, 3, 1, 4, 5, 6, 7, 1, 4, 5, 6])

    def test_ds_without_segno(self):
        measures = [M(1), M(2, ["ds_al_fine"]), M(3, ["fine"])]
        errors, _ = validate(measures)
        self.assertIn("DS_WITHOUT_SEGNO", {e.code for e in errors})
        self.assertEqual(next(e for e in errors if e.code == "DS_WITHOUT_SEGNO").measure, 2)

    def test_al_coda_without_coda_sign(self):
        measures = [M(1, ["to_coda"]), M(2, ["dc_al_coda"])]
        errors, _ = validate(measures)
        self.assertIn("MISSING_CODA_SIGN", {e.code for e in errors})

    def test_al_coda_without_to_coda(self):
        measures = [M(1, ["coda_sign"]), M(2, ["dc_al_coda"])]
        errors, _ = validate(measures)
        self.assertIn("MISSING_TO_CODA", {e.code for e in errors})

    def test_al_fine_without_fine(self):
        measures = [M(1), M(2, ["dc_al_fine"])]
        errors, _ = validate(measures)
        self.assertIn("MISSING_FINE", {e.code for e in errors})

    def test_segno_after_ds_is_illegal(self):
        measures = [M(1, ["ds_al_fine"]), M(2, ["segno"]), M(3, ["fine"])]
        errors, _ = validate(measures)
        self.assertIn("ILLEGAL_JUMP", {e.code for e in errors})

    def test_coda_sign_before_to_coda_is_illegal(self):
        measures = [
            M(1, ["coda_sign"]),
            M(2, ["to_coda"]),
            M(3, ["dc_al_coda"]),
        ]
        errors, _ = validate(measures)
        self.assertIn("ILLEGAL_JUMP", {e.code for e in errors})

    def test_multiple_jumps_rejected(self):
        measures = [
            M(1, ["fine"]),
            M(2, ["dc_al_fine"]),
            M(3, ["dc_al_fine"]),
        ]
        errors, _ = validate(measures)
        self.assertIn("MULTIPLE_JUMPS", {e.code for e in errors})


class TestLimits(unittest.TestCase):
    def test_max_steps_exceeded(self):
        measures = [M(1, ["repeat_begin"]), M(2, ["repeat_end"], repeat_times=64)]
        errors, _ = validate(measures, max_steps=10)
        self.assertEqual([e.code for e in errors], ["MAX_STEPS_EXCEEDED"])
        self.assertIsNotNone(errors[0].measure)
        with self.assertRaises(ExpansionError) as ctx:
            expand(measures, max_steps=10)
        self.assertEqual(ctx.exception.issues[0].code, "MAX_STEPS_EXCEEDED")

    def test_exact_limit_ok(self):
        measures = [M(1, ["repeat_begin"]), M(2, ["repeat_end"], repeat_times=5)]
        steps, _ = expand(measures, max_steps=10)
        self.assertEqual(len(steps), 10)
        with self.assertRaises(ExpansionError):
            expand(measures, max_steps=9)


class TestValidationDetails(unittest.TestCase):
    def test_duplicate_measure_numbers(self):
        errors, _ = validate([M(1), M(1)])
        self.assertIn("DUPLICATE_MEASURE", {e.code for e in errors})

    def test_step_events_carry_actions(self):
        measures = [M(1, ["repeat_begin"]), M(2, ["repeat_end"])]
        steps, _ = expand(measures)
        back = [s for s in steps if s.action == "repeat_back"]
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].jump_to, 1)

    def test_validate_ok(self):
        measures = [M(1), M(2, ["repeat_begin"]), M(3, ["repeat_end"])]
        errors, warnings = validate(measures)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_structure_build_never_raises_on_garbage(self):
        st = build_structure([
            M(1, ["ending_end"]),
            M(1, ["repeat_begin", "ds_al_coda"]),
            M(2, ["ending_begin"]),
        ])
        self.assertTrue(st.errors)


if __name__ == "__main__":
    unittest.main()
