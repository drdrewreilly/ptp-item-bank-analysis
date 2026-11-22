Is it possible to conduct a factor analysis on a combination of two datasets of the same items where one dataset has those items with a 7-point likert scale while the other dataset has those same items with a 5-point likert scale.

Yes, it's possible, but you can't just stack the raw scores. The two scales differ in range, and the combined dataset also carries a method difference (7-point vs 5-point), so you need to handle both.

**Key issues**

1. **Scale mismatch.** A 4 on a 7-point scale is not equivalent to a 4 on a 5-point scale. Pooling raw values would let scale format create spurious variance, and it can even produce a "method factor" in the solution.
2. **Measurement equivalence.** Even after rescaling, respondents may use 5- and 7-point formats differently (response style, midpoint use, granularity). The two formats can yield slightly different item distributions and correlations.
3. **Independence.** If the two datasets are different people, stacking them is fine. If they're the same people answering both versions, rows aren't independent, and you'd want to analyze them differently (e.g., multitrait-multimethod or a model with correlated residuals).

**Common approaches**

- **Linear rescaling (simplest).** Map both to a common range, e.g. 0-1 via (x − min)/(max − min), or to 1-5 via (x − 1) × (4/6) + 1. This is quick and widely used, but it assumes the response categories are equally spaced across formats, which is only approximately true.
- **Standardize within dataset.** Z-score each item within its own dataset before pooling. This removes mean/variance differences between formats, but it can also remove real group differences if the samples genuinely differ.
- **Treat as ordinal (recommended for rigor).** Use polychoric correlations rather than Pearson, which handle ordinal data and are less sensitive to the number of categories. With pooled data, a clean way is to compute polychoric correlation matrices separately per dataset, then compare them (or fit a multi-group CFA).
- **Multi-group CFA / measurement invariance (best practice).** Rather than pooling blindly, fit the same factor model in both groups with an ordinal estimator (e.g., WLSMV in lavaan) and test configural, metric (equal loadings), and scalar (equal thresholds) invariance. If invariance holds, pooling is justified. Because the number of thresholds differs (4 vs 6), strict threshold equality isn't directly testable. Many researchers handle this by collapsing the 7-point categories to 5 (or using IRT-based linking).

**Practical recommendation**

1. Run EFA/CFA separately on each dataset and check whether the factor structure and loadings look similar.
2. Compare the polychoric correlation matrices (e.g., via Tucker's congruence coefficient on loadings).
3. If they're comparable, rescale to a common metric (or standardize) and run the pooled factor analysis, ideally on polychoric correlations.
4. Include a dummy variable for dataset/format as a check, or report sensitivity analyses showing results hold under different rescaling choices.

**Tools:** In R, `psych::fa()` with `cor = "poly"`, `lavaan` for multi-group CFA, `mirt` for IRT-based linking. In Python, `factor_analyzer` (Pearson only) plus `semopy`, though R is stronger for ordinal and invariance work.

If you tell me whether the two datasets come from different respondents or the same ones, and roughly how many items and cases you have, I can suggest a more specific workflow and even write the code.