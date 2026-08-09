from pathlib import Path
import subprocess

try:
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
except ImportError as exc:
    raise SystemExit("Missing Python packages. Install them with: pip install -r requirements.txt") from exc

ROOT = Path(__file__).resolve().parent
DATA_DIR, OUTPUT_DIR, FIGURE_DIR = ROOT / "data", ROOT / "outputs", ROOT / "figures"
REPORT_FILE = ROOT / "report.md"
POPULATION_FILE = DATA_DIR / "weighting_population.csv.gz"
POPULATION_SIZE, SAMPLE_SIZE, SEED = 60_000, 2_400, 20260809
AGE_BANDS = ["18-29", "30-44", "45-59", "60+"]
REGIONS = ["London", "South", "Midlands", "North", "Scotland/Wales"]
EDUCATION = ["Degree", "No degree"]
BG, TEXT, MUTED, LINE, BAR, ACCENT = "#0C0C0D", "#FFFFFF", "#A2A2A9", "#313135", "#494950", "#FFFFFF"


def run_git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)


def check_repository_up_to_date():
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True, text=True)
    if inside.returncode or inside.stdout.strip() != "true":
        print("GitHub remote not detected; running analysis without repository sync.")
        return False
    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    branch = run_git("branch", "--show-current").stdout.strip()
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True)
    if origin.returncode or not branch or head.returncode:
        print("Remote branch not initialized; running analysis without repository sync.")
        return False
    run_git("fetch", "origin")
    verify = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{branch}"], cwd=ROOT)
    if verify.returncode:
        print("Remote branch not initialized; running analysis without repository sync.")
        return False
    local_only, remote_only = map(int, run_git("rev-list", "--left-right", "--count", f"HEAD...origin/{branch}").stdout.split())
    if remote_only:
        raise SystemExit(f"Your checkout is {remote_only} commit(s) behind origin/{branch}.\nRun: git pull --ff-only\nThen run: python analysis.py")
    print(f"Repository is up to date with origin/{branch}.")
    return True


def save_generated_files(sync):
    if not sync:
        return
    paths = ["report.md", "data", "outputs", "figures"]
    run_git("add", "--", *paths)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *paths], cwd=ROOT).returncode
    if changed == 0:
        print("No generated changes to commit.")
        return
    if changed != 1:
        raise SystemExit("Could not determine whether generated files changed.")
    run_git("commit", "-m", "Update demographic weighting exercise results", "--", *paths)
    branch = run_git("branch", "--show-current").stdout.strip()
    run_git("push", "origin", branch)
    print(f"Generated files committed and pushed to origin/{branch}.")


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def ensure_population():
    if POPULATION_FILE.exists():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    age = rng.choice(AGE_BANDS, POPULATION_SIZE, p=[.19, .28, .25, .28])
    region = rng.choice(REGIONS, POPULATION_SIZE, p=[.14, .25, .20, .27, .14])
    education_probability = .29 + np.where(age == "18-29", .15, 0) + np.where(age == "30-44", .10, 0) + np.where(age == "60+", -.08, 0) + np.where(region == "London", .14, 0)
    education = np.where(rng.random(POPULATION_SIZE) < education_probability, "Degree", "No degree")
    gender = rng.choice(["Woman", "Man", "Non-binary / other"], POPULATION_SIZE, p=[.505, .477, .018])
    age_effect = pd.Series(age).map({"18-29": -.55, "30-44": -.15, "45-59": .20, "60+": .48}).to_numpy()
    outcome = np.clip(np.round(5.45 + age_effect + np.where(education == "Degree", .58, -.10) + np.where(region == "London", .20, 0) + np.where(region == "North", -.12, 0) + rng.normal(0, 1.55, POPULATION_SIZE), 1), 0, 10)
    selection_score = (-.35 + np.where(age == "18-29", .18, 0) + np.where(age == "30-44", .38, 0) + np.where(age == "45-59", .62, 0) + np.where(age == "60+", -.72, 0) + np.where(education == "Degree", .78, -.18) + np.where(region == "London", .42, 0) + np.where(region == "Scotland/Wales", -.24, 0))
    probability = sigmoid(selection_score)
    probability *= SAMPLE_SIZE / probability.sum()
    probability = np.minimum(probability, .95)
    sampled = rng.choice(np.arange(POPULATION_SIZE), SAMPLE_SIZE, replace=False, p=probability / probability.sum())
    frame = pd.DataFrame({"person_id": [f"P{x:05d}" for x in range(1, POPULATION_SIZE + 1)], "age_band": age, "gender": gender, "region": region, "education": education, "policy_support_0_10": outcome, "selection_propensity": np.round(probability, 6), "sampled": 0})
    frame.loc[sampled, "sampled"] = 1
    frame.to_csv(POPULATION_FILE, index=False, compression="gzip")
    pd.DataFrame([
        ["person_id", "Synthetic person identifier"], ["age_band", "Age benchmark category"], ["gender", "Gender category"], ["region", "UK region benchmark category"], ["education", "Degree-status benchmark category"], ["policy_support_0_10", "Simulated primary survey outcome"], ["selection_propensity", "Modelled probability of sample inclusion"], ["sampled", "Achieved-sample indicator"],
    ], columns=["variable", "description"]).to_csv(DATA_DIR / "weighting_codebook.csv", index=False)
    pd.DataFrame({"parameter": ["population_size", "sample_size", "seed", "post_stratification_controls", "raking_controls", "weight_cap"], "value": [POPULATION_SIZE, SAMPLE_SIZE, SEED, "age_band x education", "age_band + region + education", 4.0]}).to_csv(DATA_DIR / "weighting_scenario.csv", index=False)


def load_population():
    frame = pd.read_csv(POPULATION_FILE)
    required = {"person_id", "age_band", "gender", "region", "education", "policy_support_0_10", "sampled"}
    missing = required - set(frame.columns)
    if missing or frame.person_id.duplicated().any() or not frame.sampled.isin([0, 1]).all() or frame.policy_support_0_10.isna().any():
        raise ValueError(f"Population validation failed; missing={sorted(missing)}")
    if len(frame) != POPULATION_SIZE or int(frame.sampled.sum()) != SAMPLE_SIZE:
        raise ValueError("Population validation failed; unexpected population or sample size")
    return frame


def normalize(weights):
    return weights * len(weights) / weights.sum()


def poststratify(sample, population):
    targets = population.groupby(["age_band", "education"]).size() / len(population)
    observed = sample.groupby(["age_band", "education"]).size() / len(sample)
    cells = pd.MultiIndex.from_frame(sample[["age_band", "education"]])
    return normalize(pd.Series(cells.map((targets / observed).to_dict()), index=sample.index, dtype=float))


def rake(sample, population, variables, cap=4.0, iterations=60):
    weights = pd.Series(1.0, index=sample.index)
    for _ in range(iterations):
        old = weights.copy()
        for variable in variables:
            target = population[variable].value_counts(normalize=True)
            current = weights.groupby(sample[variable]).sum() / weights.sum()
            weights *= sample[variable].map(target / current).astype(float)
        weights = normalize(weights.clip(1 / cap, cap))
        if np.max(np.abs(weights - old)) < 1e-8:
            break
    return weights


def weighted_mean(values, weights):
    return np.average(values, weights=weights)


def analyse(population):
    sample = population[population.sampled.eq(1)].copy()
    sample["poststrat_weight"] = poststratify(sample, population)
    sample["raked_weight"] = rake(sample, population, ["age_band", "region", "education"])
    benchmark = population.policy_support_0_10.mean()
    estimates = pd.DataFrame([
        ["Population benchmark", benchmark, 0.0],
        ["Unweighted", sample.policy_support_0_10.mean(), sample.policy_support_0_10.mean() - benchmark],
        ["Post-stratified", weighted_mean(sample.policy_support_0_10, sample.poststrat_weight), weighted_mean(sample.policy_support_0_10, sample.poststrat_weight) - benchmark],
        ["Raked", weighted_mean(sample.policy_support_0_10, sample.raked_weight), weighted_mean(sample.policy_support_0_10, sample.raked_weight) - benchmark],
    ], columns=["estimate", "mean_policy_support", "bias"])
    rows = []
    for variable in ["age_band", "gender", "region", "education"]:
        for category in population[variable].value_counts().index:
            mask = sample[variable].eq(category)
            pop_share = population[variable].eq(category).mean()
            raw_share = mask.mean()
            post_share = sample.loc[mask, "poststrat_weight"].sum() / sample.poststrat_weight.sum()
            rake_share = sample.loc[mask, "raked_weight"].sum() / sample.raked_weight.sum()
            rows.append([variable, category, pop_share, raw_share, post_share, rake_share, 100*(raw_share-pop_share), 100*(post_share-pop_share), 100*(rake_share-pop_share)])
    composition = pd.DataFrame(rows, columns=["variable", "category", "population_share", "unweighted_share", "poststratified_share", "raked_share", "unweighted_difference_pp", "poststratified_difference_pp", "raked_difference_pp"])
    diagnostics = []
    for method, column in [("Unweighted", None), ("Post-stratified", "poststrat_weight"), ("Raked", "raked_weight")]:
        weights = np.ones(len(sample)) if column is None else sample[column].to_numpy()
        deff = len(weights) * np.square(weights).sum() / weights.sum() ** 2
        ess = len(weights) / deff
        diagnostics.append([method, weights.min(), np.quantile(weights, .25), np.median(weights), np.quantile(weights, .75), np.quantile(weights, .95), weights.max(), deff, ess, (weights > 3).mean()])
    diagnostics = pd.DataFrame(diagnostics, columns=["method", "minimum_weight", "p25_weight", "median_weight", "p75_weight", "p95_weight", "maximum_weight", "design_effect", "effective_sample_size", "share_weights_above_3"])
    crosstab = sample.groupby(["age_band", "education"], observed=True).apply(lambda x: pd.Series({"sample_n": len(x), "population_mean": population.loc[(population.age_band.eq(x.name[0])) & (population.education.eq(x.name[1])), "policy_support_0_10"].mean(), "unweighted_mean": x.policy_support_0_10.mean(), "poststratified_mean": weighted_mean(x.policy_support_0_10, x.poststrat_weight), "raked_mean": weighted_mean(x.policy_support_0_10, x.raked_weight)}), include_groups=False).reset_index()
    return sample, estimates, composition, diagnostics, crosstab


def style(ax, axis="y"):
    ax.figure.patch.set_facecolor(BG); ax.set_facecolor(BG); ax.tick_params(colors=MUTED, labelsize=9.5, length=0, pad=7)
    ax.xaxis.label.set_color(MUTED); ax.yaxis.label.set_color(MUTED); ax.title.set_color(TEXT)
    for spine in ax.spines.values(): spine.set_visible(False)
    ax.grid(axis=axis, color=LINE, linewidth=.8, alpha=.65); ax.set_axisbelow(True)


def create_figures(sample, estimates, composition, diagnostics):
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    summary = composition.groupby("variable")[["unweighted_difference_pp", "poststratified_difference_pp", "raked_difference_pp"]].apply(lambda x: x.abs().mean())
    fig, ax = plt.subplots(figsize=(9.6, 5.6)); style(ax)
    x = np.arange(len(summary)); width = .25
    ax.bar(x-width, summary.unweighted_difference_pp, width, color=BAR, label="Unweighted")
    ax.bar(x, summary.poststratified_difference_pp, width, color=MUTED, label="Post-stratified")
    ax.bar(x+width, summary.raked_difference_pp, width, color=ACCENT, label="Raked")
    ax.set_xticks(x, [v.replace("_", " ").title() for v in summary.index]); ax.set_ylabel("Mean absolute deviation (percentage points)", labelpad=12); ax.set_title("Weighting restores demographic alignment", loc="left", pad=18, fontsize=16, fontweight=400, color=TEXT)
    legend = ax.legend(frameon=False); [t.set_color(MUTED) for t in legend.get_texts()]
    fig.tight_layout(pad=1.6); fig.savefig(FIGURE_DIR / "composition_before_after_weighting.png", dpi=200, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9.6, 5.6)); style(ax)
    values = estimates.mean_policy_support; bars = ax.bar(estimates.estimate, values, color=[ACCENT, BAR, MUTED, TEXT], width=.58)
    ax.set_ylim(values.min()-.25, values.max()+.25); ax.set_ylabel("Mean policy support (0–10)", labelpad=12); ax.set_title("Weighted estimates move towards the benchmark", loc="left", pad=18, fontsize=16, fontweight=400, color=TEXT)
    for bar, value in zip(bars, values): ax.text(bar.get_x()+bar.get_width()/2, value+.025, f"{value:.3f}", ha="center", color=TEXT)
    fig.tight_layout(pad=1.6); fig.savefig(FIGURE_DIR / "weighted_unweighted_estimates.png", dpi=200, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9.6, 5.6)); style(ax, "y")
    bins = np.linspace(.2, 4, 24); ax.hist(sample.poststrat_weight, bins=bins, color=BAR, alpha=.85, label="Post-stratified"); ax.hist(sample.raked_weight, bins=bins, color=ACCENT, alpha=.55, label="Raked")
    ax.axvline(1, color=MUTED, linewidth=1); ax.set_xlabel("Normalised survey weight", labelpad=12); ax.set_ylabel("Respondents", labelpad=12); ax.set_title("Weight distributions reveal the precision cost", loc="left", pad=18, fontsize=16, fontweight=400, color=TEXT)
    legend = ax.legend(frameon=False); [t.set_color(MUTED) for t in legend.get_texts()]
    fig.tight_layout(pad=1.6); fig.savefig(FIGURE_DIR / "weight_distributions.png", dpi=200, facecolor=BG, bbox_inches="tight"); plt.close(fig)


def generate_report(population, sample, estimates, composition, diagnostics):
    e = estimates.set_index("estimate")
    d = diagnostics.set_index("method")
    raw_bias, post_bias, rake_bias = abs(e.loc["Unweighted", "bias"]), abs(e.loc["Post-stratified", "bias"]), abs(e.loc["Raked", "bias"])
    comp = composition.groupby("variable")[["unweighted_difference_pp", "poststratified_difference_pp", "raked_difference_pp"]].apply(lambda x: x.abs().mean())
    report = f"""# Demographic Weighting Exercise

## Project Snapshot

| Project type | Dataset | Tools | Outputs |
|---|---|---|---|
| Simulated Quantitative Case Study | {len(population):,}-Person Synthetic UK Adult Population; {len(sample):,}-Person Achieved Survey Sample | Python / Pandas / NumPy / Matplotlib | Benchmark Audit; Post-stratification; Raking; Weighted Estimates; Design-Effect Diagnostics; Dark Figures |

**Skills demonstrated:** Data Weighting · Statistical Analysis · Sampling · Data Cleaning · Data Validation · Cross-tabulation

## Study Context

This simulated case study starts with a known UK adult population and an achieved survey sample whose selection process overrepresents working-age, degree-educated and London respondents. The population totals are treated as external benchmark controls. All values are synthetic and are not estimates of the real UK population.

## Objective and Method

The study audits unweighted composition, applies two adjustment strategies, and tests whether demographic correction improves a mean policy-support estimate. Post-stratification calibrates the joint age-by-education cells. Iterative proportional fitting (raking) calibrates age, region and education margins, with normalised weights capped at 4.0. Validation checks cover schema, unique identifiers, missing outcomes and expected sample counts.

## Composition Audit

| Benchmark variable | Unweighted mean absolute difference | Post-stratified | Raked |
|---|---:|---:|---:|
""" + "\n".join(f"| {v.replace('_', ' ').title()} | {row.unweighted_difference_pp:.2f} pp | {row.poststratified_difference_pp:.2f} pp | {row.raked_difference_pp:.2f} pp |" for v, row in comp.iterrows()) + f"""

Post-stratification exactly aligns age and education jointly but leaves region imbalance. Raking aligns all three specified margins; gender remains an audit variable rather than a weighting control, illustrating that calibration only guarantees balance on included benchmarks.

## Weighted and Unweighted Estimates

| Estimate | Mean policy support | Bias versus population |
|---|---:|---:|
| Population benchmark | {e.loc['Population benchmark','mean_policy_support']:.3f} | — |
| Unweighted sample | {e.loc['Unweighted','mean_policy_support']:.3f} | {e.loc['Unweighted','bias']:+.3f} |
| Post-stratified sample | {e.loc['Post-stratified','mean_policy_support']:.3f} | {e.loc['Post-stratified','bias']:+.3f} |
| Raked sample | {e.loc['Raked','mean_policy_support']:.3f} | {e.loc['Raked','bias']:+.3f} |

Post-stratification reduces absolute bias by {(raw_bias-post_bias)/raw_bias*100:.1f}%; raking reduces it by {(raw_bias-rake_bias)/raw_bias*100:.1f}%. The correction works because the outcome is associated with demographics that also shaped selection, but neither method can guarantee removal of selection effects within weighting cells.

## Weight Diagnostics and Bias–Variance Trade-off

| Method | Minimum | Median | 95th percentile | Maximum | Design effect | Effective sample size |
|---|---:|---:|---:|---:|---:|---:|
| Unweighted | 1.00 | 1.00 | 1.00 | 1.00 | 1.000 | {d.loc['Unweighted','effective_sample_size']:,.0f} |
| Post-stratified | {d.loc['Post-stratified','minimum_weight']:.2f} | {d.loc['Post-stratified','median_weight']:.2f} | {d.loc['Post-stratified','p95_weight']:.2f} | {d.loc['Post-stratified','maximum_weight']:.2f} | {d.loc['Post-stratified','design_effect']:.3f} | {d.loc['Post-stratified','effective_sample_size']:,.0f} |
| Raked | {d.loc['Raked','minimum_weight']:.2f} | {d.loc['Raked','median_weight']:.2f} | {d.loc['Raked','p95_weight']:.2f} | {d.loc['Raked','maximum_weight']:.2f} | {d.loc['Raked','design_effect']:.3f} | {d.loc['Raked','effective_sample_size']:,.0f} |

Weighting trades variance for reduced demographic and outcome bias. The raked estimate is closer to the known population value, while unequal weights reduce the nominal {len(sample):,} interviews to an effective sample size of {d.loc['Raked','effective_sample_size']:,.0f}. The 4.0 cap limits domination by sparse profiles; this protects precision but may leave small residual discrepancies when a target requires more correction.

## Interpretation

For reporting, the raked weight is the preferred general-purpose weight because it matches more benchmark dimensions and achieves the smallest outcome bias in this simulation. Post-stratification remains useful when reliable joint population cells are available, but increasingly granular cells can become sparse. The decision should therefore consider benchmark quality, cell size, extreme weights, effective sample size and whether the weighting variables plausibly explain both selection and the outcome.

## Figures

### Composition before and after weighting

![Composition before and after weighting](figures/composition_before_after_weighting.png)

### Weighted and unweighted estimates

![Weighted and unweighted estimates](figures/weighted_unweighted_estimates.png)

### Weight distributions

![Weight distributions](figures/weight_distributions.png)

## Project Files

- [`data/weighting_population.csv.gz`](data/weighting_population.csv.gz) — known synthetic population with achieved-sample indicator.
- [`data/weighting_codebook.csv`](data/weighting_codebook.csv) — variable definitions.
- [`data/weighting_scenario.csv`](data/weighting_scenario.csv) — deterministic simulation and weighting parameters.
- [`outputs/respondents_weighted.csv`](outputs/respondents_weighted.csv) — respondent-level file with both final weights.
- [`outputs/population_benchmarks.csv`](outputs/population_benchmarks.csv) — benchmark, unweighted and weighted composition shares.
- [`outputs/estimate_comparison.csv`](outputs/estimate_comparison.csv) — benchmark and survey estimates with bias.
- [`outputs/weight_diagnostics.csv`](outputs/weight_diagnostics.csv) — weight percentiles, design effects and effective sample sizes.
- [`outputs/weighted_crosstabs.csv`](outputs/weighted_crosstabs.csv) — age-by-education estimates for validation and interpretation.
"""
    REPORT_FILE.write_text(report.strip()+"\n", encoding="utf-8")


def main():
    sync = check_repository_up_to_date(); OUTPUT_DIR.mkdir(parents=True, exist_ok=True); ensure_population(); population = load_population()
    sample, estimates, composition, diagnostics, crosstab = analyse(population)
    sample.to_csv(OUTPUT_DIR / "respondents_weighted.csv", index=False)
    composition.to_csv(OUTPUT_DIR / "population_benchmarks.csv", index=False)
    estimates.to_csv(OUTPUT_DIR / "estimate_comparison.csv", index=False)
    diagnostics.to_csv(OUTPUT_DIR / "weight_diagnostics.csv", index=False)
    crosstab.to_csv(OUTPUT_DIR / "weighted_crosstabs.csv", index=False)
    create_figures(sample, estimates, composition, diagnostics); generate_report(population, sample, estimates, composition, diagnostics)
    print("Demographic Weighting Exercise\n==============================")
    print(f"Population: {len(population):,}\nAchieved sample: {len(sample):,}")
    for _, row in estimates.iterrows(): print(f"  {row.estimate}: {row.mean_policy_support:.3f} (bias {row.bias:+.3f})")
    print("\nReport written to: report.md\nOutputs saved to: outputs/\nFigures saved to: figures/")
    save_generated_files(sync)


if __name__ == "__main__":
    main()
