from erbuild.cli import main


def test_ar(capsys):
    assert main(["ar", "Blood Uchigatana", "--str", "12", "--dex", "40", "--arc", "50"]) == 0
    out = capsys.readouterr().out
    assert "Physical       445" in out
    assert "Bleed          110" in out


def test_optimize_frontier(capsys):
    args = ["optimize", "Blood Uchigatana", "--class", "samurai", "--level", "150", "--vig", "60"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Highest AR:" in out
    assert "Pareto-optimal builds" in out
    assert "VIG 60" in out


def test_optimize_min_buildup(capsys):
    args = ["optimize", "Blood Uchigatana", "--class", "samurai", "-l", "150", "--vig", "60",
            "--min-buildup", "110", "--min", "mnd=20"]
    assert main(args) == 0
    assert "Highest AR with Bleed >= 110" in capsys.readouterr().out


def test_optimize_errors(capsys):
    assert main(["optimize", "Uchigatana", "--class", "samurai", "-l", "5"]) == 1
    assert "too low" in capsys.readouterr().err
    assert main(["optimize", "Uchigatana", "--class", "samurai", "-l", "50", "--min", "foo"]) == 1
    assert "STAT=N" in capsys.readouterr().err
    assert main(["optimize", "Uchigatan", "--class", "samurai", "-l", "50"]) == 1
    assert "Did you mean" in capsys.readouterr().err
    assert main(["optimize", "Heavy Claymore", "--class", "hero", "-l", "50", "--min-buildup", "5"]) == 1
    assert "no status buildup" in capsys.readouterr().err
