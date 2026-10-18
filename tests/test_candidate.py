from ci_triage.candidate import LABEL_HEADER, update_label_sheet


def test_label_sheet_starts_blank(tmp_path):
    sheet = tmp_path / "labels.tsv"
    update_label_sheet(sheet, ["s01/pass-1", "s01/cause-1"])
    assert sheet.read_text(encoding="utf-8").splitlines() == [
        LABEL_HEADER,
        "s01/cause-1\t\t",
        "s01/pass-1\t\t",
    ]


def test_label_sheet_keeps_hand_labels_and_adds_new_runs(tmp_path):
    sheet = tmp_path / "labels.tsv"
    sheet.write_text(
        f"{LABEL_HEADER}\ns01/cause-1\tfix\t\ns06/cause-3\tunsure\tbranch name hinted\n",
        encoding="utf-8",
    )
    update_label_sheet(sheet, ["s01/cause-1", "s01/cause-2", "s06/cause-3"])
    assert sheet.read_text(encoding="utf-8").splitlines() == [
        LABEL_HEADER,
        "s01/cause-1\tfix\t",
        "s01/cause-2\t\t",
        "s06/cause-3\tunsure\tbranch name hinted",
    ]
