import unittest

from tools.import_markdown import prepare_source_only_candidate


class OcclusionNormalizationTests(unittest.TestCase):
    def normalize(self, text: str) -> tuple[str, list[dict]]:
        return prepare_source_only_candidate(text + "\n", {})

    def test_complete_term_variants_are_normalized(self) -> None:
        output, _changes = self.normalize(
            "验面 上骑架 体验支托 平衡雅 酷接触 牙列、验与颌位 第二节验"
        )
        self.assertEqual(
            output,
            "𬌗面 上𬌗架 𬌗支托 平衡𬌗 𬌗接触 牙列、𬌗与颌位 第二节𬌗\n",
        )

    def test_legitimate_words_overlapping_aliases_are_preserved(self) -> None:
        source = "实验架 检验面 优雅面容 骑跨 体验 咬合 经验 试验"
        output, changes = self.normalize(source)
        self.assertEqual(output, source + "\n")
        self.assertEqual(changes, [])

    def test_only_high_confidence_missing_glyphs_are_restored(self) -> None:
        output, _changes = self.normalize(
            "错畸形 深覆 深覆盖 浅覆 浅覆盖 覆覆盖 前牙开畸形 组牙功能 咬接触 "
            "牙尖交错（intercuspal occlusion） 扭转等错。覆及覆盖 牙间隙、开、牙松动 "
            "严重的错、难以消除的夜磨牙 对刃、锁验"
        )
        self.assertEqual(
            output,
            "错𬌗畸形 深覆𬌗 深覆盖 浅覆𬌗 浅覆盖 覆𬌗覆盖 前牙开畸形 组牙功能 咬接触 "
            "牙尖交错𬌗（intercuspal occlusion） 扭转等错𬌗。覆𬌗及覆盖 牙间隙、开𬌗、牙松动 "
            "严重的错𬌗、难以消除的夜磨牙 对刃𬌗、锁𬌗\n",
        )

    def test_occlusion_establishment_phrases_are_restored(self) -> None:
        output, _changes = self.normalize(
            "都会影响建。影响建的关键因素。乳牙建约在2岁半完成。"
            "萌出建，恒牙𬌗建早期，建后易于维持。"
            "正中关系建。上下颌牙建的初期。"
        )
        self.assertEqual(
            output,
            "都会影响𬌗的建立。影响𬌗建立的关键因素。乳牙𬌗建立约在2岁半完成。"
            "萌出建𬌗，恒牙𬌗建立早期，建𬌗后易于维持。"
            "正中关系建𬌗。上下颌牙𬌗建立的初期。\n",
        )

    def test_bare_confusion_characters_are_never_replaced(self) -> None:
        source = "验 骑 矜 雅 酷 合 咬"
        output, changes = self.normalize(source)
        self.assertEqual(output, source + "\n")
        self.assertEqual(changes, [])

    def test_restorative_cavity_terms_are_normalized(self) -> None:
        output, _changes = self.normalize(
            "邻验洞 邻雅邻洞 邻酷面洞 矜壁 验轴线角 颊(腭)酷洞"
        )
        self.assertEqual(
            output,
            "邻𬌗洞 邻𬌗邻洞 邻𬌗面洞 𬌗壁 𬌗轴线角 颊(腭)𬌗洞\n",
        )

    def test_fixed_watermark_lines_are_removed(self) -> None:
        output, changes = self.normalize(
            "正文第一行\n本资料仅用于学习交流使用，禁止用于商业用途\n正文第二行"
        )
        self.assertEqual(output, "正文第一行\n\n正文第二行\n")
        self.assertEqual(changes[0]["kind"], "remove_scan_metadata_line")

    def test_ocr_stuck_watermark_variants_are_removed(self) -> None:
        output, changes = self.normalize(
            "正文\n资料仅用干学习交流使用，禁止用于商业用途\n正文"
        )
        self.assertEqual(output, "正文\n\n正文\n")
        self.assertEqual(changes[0]["kind"], "remove_scan_metadata_line")


if __name__ == "__main__":
    unittest.main()
