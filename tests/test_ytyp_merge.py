"""Mehrere .ytyp zu einer Sammel-ytyp zusammenfassen."""
import argparse

import pytest

from propforge import cli, ytyp_merge


def write_ytyp(path, name, archetypes):
    """Schreibt eine .ytyp.xml, wie CodeWalker und Sollumz sie ausgeben.

    Bewusst als Datei und nicht als vorgefertigtes Objekt: der Merger soll
    gegen das Format getestet werden, das er im Betrieb sieht - inklusive der
    Eigenheit, dass Zahlen als Attribut und Zeichenketten als Textinhalt
    notiert sind.
    """
    items = "\n".join(
        f"""    <Item type="CBaseArchetypeDef">
      <lodDist value="{lod}" />
      <flags value="32" />
      <specialAttribute value="0" />
      <bbMin x="-1" y="-1" z="0" />
      <bbMax x="1" y="1" z="2" />
      <bsCentre x="0" y="0" z="1" />
      <bsRadius value="1.7" />
      <name>{arch}</name>
      <textureDictionary>{txd}</textureDictionary>
      <physicsDictionary>{arch}</physicsDictionary>
      <assetType>ASSET_TYPE_DRAWABLE</assetType>
      <assetName>{arch}</assetName>
    </Item>"""
        for arch, lod, txd in archetypes)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<CMapTypes>\n  <extensions />\n  <archetypes>\n{items}\n  </archetypes>\n"
        f"  <name>{name}</name>\n  <dependencies />\n  <compositeEntityTypes />\n"
        "</CMapTypes>\n",
        encoding="utf-8")
    return path


def crate(tmp_path, stem, arch, lod=500, txd=""):
    return write_ytyp(tmp_path / f"{stem}.ytyp.xml", f"{stem}", [(arch, lod, txd)])


class TestReading:
    def test_archetypes_are_found(self, tmp_path):
        path = crate(tmp_path, "pf_crate_ityp", "pf_crate")
        entries = ytyp_merge.read_archetypes(path)
        assert [e.name for e in entries] == ["pf_crate"]

    def test_broken_xml_is_named(self, tmp_path):
        path = tmp_path / "kaputt.ytyp.xml"
        path.write_text("<CMapTypes><archetypes>", encoding="utf-8")
        with pytest.raises(ytyp_merge.MergeError, match="kein gueltiges XML"):
            ytyp_merge.read_archetypes(path)

    def test_wrong_root_element_is_refused(self, tmp_path):
        """Eine .ydr.xml sieht von aussen aus wie eine .ytyp.xml."""
        path = tmp_path / "falsch.ytyp.xml"
        path.write_text('<?xml version="1.0"?>\n<Drawable />\n', encoding="utf-8")
        with pytest.raises(ytyp_merge.MergeError, match="CMapTypes"):
            ytyp_merge.read_archetypes(path)

    def test_nameless_archetype_is_refused(self, tmp_path):
        """Ohne Namen ist ein Archetyp im Spiel nicht referenzierbar."""
        path = tmp_path / "leer.ytyp.xml"
        path.write_text(
            '<?xml version="1.0"?>\n<CMapTypes><archetypes>'
            '<Item type="CBaseArchetypeDef"><lodDist value="10" /></Item>'
            "</archetypes></CMapTypes>\n", encoding="utf-8")
        with pytest.raises(ytyp_merge.MergeError, match="ohne <name>"):
            ytyp_merge.read_archetypes(path)


class TestMerging:
    def test_two_files_become_one(self, tmp_path):
        paths = [crate(tmp_path, "a_ityp", "pf_crate"),
                 crate(tmp_path, "b_ityp", "pf_barrel")]
        out = tmp_path / "pack.ytyp.xml"
        plan = ytyp_merge.merge(paths, "pack_props", out)

        assert plan.archetype_names == ["pf_crate", "pf_barrel"]
        assert out.is_file()
        # Die Gegenprobe, die zaehlt: die geschriebene Datei zurueckgelesen.
        reread = ytyp_merge.read_archetypes(out)
        assert [e.name for e in reread] == ["pf_crate", "pf_barrel"]

    def test_merged_file_carries_the_new_name(self, tmp_path):
        paths = [crate(tmp_path, "a_ityp", "pf_crate")]
        out = tmp_path / "pack.ytyp.xml"
        ytyp_merge.merge(paths, "pack_props", out)
        assert "<name>pack_props</name>" in out.read_text()

    def test_archetype_fields_survive(self, tmp_path):
        """Zusammenfassen heisst umhaengen, nicht neu schreiben.

        Ginge dabei ein Feld verloren - eine lodDist, ein
        textureDictionary -, waere das im Spiel ein anderer Prop, ohne dass
        eine Datei fehlt.
        """
        paths = [crate(tmp_path, "a_ityp", "pf_crate", lod=123, txd="pack_props")]
        out = tmp_path / "pack.ytyp.xml"
        ytyp_merge.merge(paths, "pack_props", out)
        text = out.read_text()
        assert 'value="123"' in text
        assert "<textureDictionary>pack_props</textureDictionary>" in text

    def test_identical_duplicates_are_taken_once(self, tmp_path):
        """Derselbe Prop zweimal gebaut: die Wahl ist folgenlos."""
        a = crate(tmp_path, "a_ityp", "pf_crate")
        b = write_ytyp(tmp_path / "b_ityp.ytyp.xml", "b_ityp", [("pf_crate", 500, "")])
        plan = ytyp_merge.merge([a, b], "pack_props", tmp_path / "pack.ytyp.xml")
        assert plan.archetype_names == ["pf_crate"]
        assert plan.duplicates == ["pf_crate"]

    def test_conflicting_duplicates_stop_the_merge(self, tmp_path):
        """Der teure Fall: gleicher Name, andere Definition.

        Im Spiel gewinnt der zuletzt geladene Archetyp - welcher das ist,
        entscheidet die Ladereihenfolge. Ein Prop zeigt dann das Modell eines
        anderen, und nichts meldet einen Fehler. Deshalb Abbruch statt einer
        stillen Entscheidung.
        """
        a = crate(tmp_path, "a_ityp", "pf_crate", lod=500)
        b = crate(tmp_path, "b_ityp", "pf_crate", lod=120)
        with pytest.raises(ytyp_merge.MergeError, match="zweimal|verschiedene"):
            ytyp_merge.merge([a, b], "pack_props", tmp_path / "pack.ytyp.xml")

    def test_conflict_names_both_files(self, tmp_path):
        """Die Fehlermeldung muss sagen, wo man suchen soll."""
        a = crate(tmp_path, "a_ityp", "pf_crate", lod=500)
        b = crate(tmp_path, "b_ityp", "pf_crate", lod=120)
        with pytest.raises(ytyp_merge.MergeError) as exc:
            ytyp_merge.plan_merge([a, b], "pack_props")
        assert "a_ityp.ytyp.xml" in str(exc.value)
        assert "b_ityp.ytyp.xml" in str(exc.value)

    def test_nothing_to_merge_is_refused(self, tmp_path):
        empty = tmp_path / "leer.ytyp.xml"
        empty.write_text(
            '<?xml version="1.0"?>\n<CMapTypes><archetypes /></CMapTypes>\n',
            encoding="utf-8")
        with pytest.raises(ytyp_merge.MergeError, match="Keine Archetypen"):
            ytyp_merge.merge([empty], "pack_props", tmp_path / "pack.ytyp.xml")

    def test_empty_file_is_reported_as_skipped(self, tmp_path):
        empty = tmp_path / "leer.ytyp.xml"
        empty.write_text(
            '<?xml version="1.0"?>\n<CMapTypes><archetypes /></CMapTypes>\n',
            encoding="utf-8")
        plan = ytyp_merge.plan_merge(
            [empty, crate(tmp_path, "a_ityp", "pf_crate")], "pack_props")
        assert [p.name for p, _ in plan.skipped] == ["leer.ytyp.xml"]
        assert plan.archetype_names == ["pf_crate"]

    def test_sixty_props_stay_sixty_archetypes(self, tmp_path):
        """Der eigentliche Anwendungsfall: ein Pack."""
        paths = [crate(tmp_path, f"p{i:02d}_ityp", f"pf_prop{i:02d}") for i in range(60)]
        out = tmp_path / "pack.ytyp.xml"
        plan = ytyp_merge.merge(paths, "pack_props", out)
        assert len(plan.entries) == 60
        assert len(ytyp_merge.read_archetypes(out)) == 60


class TestFinding:
    def test_only_ytyp_xml_is_picked_up(self, tmp_path):
        crate(tmp_path, "a_ityp", "pf_crate")
        (tmp_path / "pf_crate.ydr.xml").write_text("<Drawable />", encoding="utf-8")
        (tmp_path / "notiz.txt").write_text("x", encoding="utf-8")
        assert [p.name for p in ytyp_merge.find_ytyps(tmp_path)] == ["a_ityp.ytyp.xml"]


class TestCommand:
    def _args(self, tmp_path, **overrides):
        args = dict(source=str(tmp_path), name="pack_props", out=None, blender=None,
                    format="CWXML", version="GEN8", dry_run=False)
        args.update(overrides)
        return argparse.Namespace(**args)

    def test_folder_of_xml_needs_no_blender(self, tmp_path):
        crate(tmp_path, "a_ityp", "pf_crate")
        crate(tmp_path, "b_ityp", "pf_barrel")
        assert cli.cmd_merge_ytyp(self._args(tmp_path)) == 0
        out = tmp_path / "merged" / "pack_props.ytyp.xml"
        assert [e.name for e in ytyp_merge.read_archetypes(out)] == ["pf_crate", "pf_barrel"]

    def test_dry_run_writes_nothing(self, tmp_path):
        crate(tmp_path, "a_ityp", "pf_crate")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, dry_run=True)) == 0
        assert not (tmp_path / "merged").exists()

    def test_conflict_returns_failure(self, tmp_path):
        crate(tmp_path, "a_ityp", "pf_crate", lod=500)
        crate(tmp_path, "b_ityp", "pf_crate", lod=120)
        assert cli.cmd_merge_ytyp(self._args(tmp_path)) == 1

    def test_empty_folder_is_reported(self, tmp_path):
        assert cli.cmd_merge_ytyp(self._args(tmp_path)) == 2

    def test_missing_folder_is_reported(self, tmp_path):
        args = self._args(tmp_path, source=str(tmp_path / "gibtsnicht"))
        assert cli.cmd_merge_ytyp(args) == 2

    def test_name_is_normalised(self, tmp_path):
        crate(tmp_path, "a_ityp", "pf_crate")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, name="Pack Props")) == 0
        assert (tmp_path / "merged" / "pack_props.ytyp.xml").is_file()

    def test_folder_name_is_the_default(self, tmp_path):
        folder = tmp_path / "Mein Pack"
        folder.mkdir()
        crate(folder, "a_ityp", "pf_crate")
        assert cli.cmd_merge_ytyp(self._args(folder, name=None)) == 0
        assert (folder / "merged" / "mein_pack.ytyp.xml").is_file()

    def test_second_run_does_not_fold_in_its_own_result(self, tmp_path):
        """Ein Prop ist dazugekommen - also nochmal laufen lassen.

        Mit --out auf denselben Ordner laege das Ergebnis des ersten Laufs
        beim zweiten als Eingabe da. Jeder Archetyp waere dann doppelt, und
        weil die Kopien identisch sind, faellt es nicht einmal als Konflikt
        auf - die Sammel-ytyp waere still falsch.
        """
        crate(tmp_path, "a_ityp", "pf_crate")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, out=str(tmp_path))) == 0
        crate(tmp_path, "b_ityp", "pf_barrel")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, out=str(tmp_path))) == 0
        out = tmp_path / "pack_props.ytyp.xml"
        assert [e.name for e in ytyp_merge.read_archetypes(out)] == ["pf_crate", "pf_barrel"]

    def test_only_own_result_left_is_reported(self, tmp_path):
        crate(tmp_path, "a_ityp", "pf_crate")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, out=str(tmp_path))) == 0
        for path in tmp_path.iterdir():
            if path.name != "pack_props.ytyp.xml":
                path.unlink()
        assert cli.cmd_merge_ytyp(self._args(tmp_path, out=str(tmp_path))) == 2

    def test_binary_input_without_blender_is_refused(self, tmp_path):
        """Ohne szio geht die Binaerform nicht - das muss dastehen.

        Wichtiger als der Rueckgabewert ist, dass hier nichts halb Fertiges
        geschrieben wird: eine Sammel-ytyp, in der nur die XML-Dateien
        gelandet sind, waere schlimmer als gar keine.
        """
        crate(tmp_path, "a_ityp", "pf_crate")
        (tmp_path / "b_ityp.ytyp").write_bytes(b"RSC7 dummy")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, format="NATIVE")) == 2
        assert not (tmp_path / "merged").exists()

    def test_native_output_needs_blender_even_for_xml_input(self, tmp_path):
        """CWXML lesen und NATIVE schreiben kann nur szio."""
        crate(tmp_path, "a_ityp", "pf_crate")
        assert cli.cmd_merge_ytyp(self._args(tmp_path, format="NATIVE")) == 2

    def test_dry_run_is_refused_for_binaries(self, tmp_path):
        (tmp_path / "b_ityp.ytyp").write_bytes(b"RSC7 dummy")
        args = self._args(tmp_path, format="NATIVE", dry_run=True)
        assert cli.cmd_merge_ytyp(args) == 2
