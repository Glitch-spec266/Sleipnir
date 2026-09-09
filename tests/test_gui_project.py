from sleipnir.gui_project import create_project_plan


def test_project_goal_stays_inside_python_boundary_not_process_argv(tmp_path):
    captured = []

    def runner(argv):
        captured.append(argv)
        print("wrote plan.json — 3 tasks")
        return 0

    result = create_project_plan("Build a clean desktop app", workspace=tmp_path, runner=runner)

    assert result["status"] == "complete"
    assert captured == [["--run-root", str(tmp_path.resolve()), "plan", "Build a clean desktop app"]]


def test_project_creation_refuses_to_replace_an_existing_plan(tmp_path):
    (tmp_path / "plan.json").write_text("{}")

    try:
        create_project_plan("Replace it", workspace=tmp_path, runner=lambda _: 0)
    except ValueError as error:
        assert "already has a plan" in str(error)
    else:
        raise AssertionError("existing plan was not protected")
