import main


def test_title_in_library_true_when_folder_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    (tmp_path / main.sanitize("Matt Dinniman") / main.sanitize("Dungeon Crawler Carl")).mkdir(parents=True)
    assert main.title_in_library("Matt Dinniman", "Dungeon Crawler Carl", "audiobook") is True


def test_title_in_library_false_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    assert main.title_in_library("Nobody", "No Such Book", "audiobook") is False


def test_title_in_library_uses_sanitized_names(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    (tmp_path / main.sanitize("A") / main.sanitize("Book: One/Two")).mkdir(parents=True)
    assert main.title_in_library("A", "Book: One/Two", "audiobook") is True


def test_title_in_library_checks_both_ebook_dirs(monkeypatch, tmp_path):
    send = tmp_path / "send"; nosend = tmp_path / "nosend"
    send.mkdir(); nosend.mkdir()
    monkeypatch.setattr(main.settings, "EBOOKS_DIR", str(send))
    monkeypatch.setattr(main.settings, "EBOOKS_NOSEND_DIR", str(nosend))
    (nosend / main.sanitize("Herbert") / main.sanitize("Dune")).mkdir(parents=True)
    assert main.title_in_library("Herbert", "Dune", "ebook") is True


def test_title_in_library_empty_title_is_false(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "LIBRARY_DIR", str(tmp_path))
    assert main.title_in_library("Someone", "", "audiobook") is False
