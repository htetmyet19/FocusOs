# Title classifier: model report

Generated 2026-11-21 21:53 by `python ai/title_classifier.py train`.

**Data:** 614 labelled titles in 57 groups ({'demo': 614}); labels {'productive': 262, 'neutral': 146, 'distracting': 206}.

> **614 of the titles are generated demo data.** These numbers show that the pipeline works and that the evaluation is honest; they are *not* an estimate of accuracy on your real browsing. Label real titles (`source = 'user'`) and retrain with `--source user` to measure that.

## Two questions

- **Known sites:** a new title from a site or pattern the model has seen examples of (cross-validation grouped by exact title, so no duplicate is on both sides). The common case.
- **Unseen sites:** a title from a site or pattern it has never seen (cross-validation grouped by template). The hard case.

Real use falls in between: most browsing is on a handful of familiar sites, plus the occasional new one.

## Model comparison (macro-F1, 5-fold grouped cross-validation)

| Model | Known sites | Unseen sites | Log loss (unseen) |
|---|---|---|---|
| Complement NB, words + chars **(chosen)** | 0.884 | 0.699 | 0.997 |
| Logistic regression, words + chars (C=1) | 0.879 | 0.639 | 0.819 |
| Logistic regression, words + chars (C=5) | 0.876 | 0.619 | 0.828 |
| Linear SVM, words + chars (calibrated) | 0.864 | 0.592 | 0.916 |
| Naive Bayes, words (previous model) | 0.842 | 0.560 | 0.760 |
| Majority class (baseline) | 0.199 | 0.199 | 7.920 |

**Headline estimate for unseen sites (nested grouped CV): macro-F1 0.679 +/- 0.102.** The model was chosen inside each outer fold without seeing that fold's templates (choices: Complement NB, words + chars (5x)), so this number is not inflated by picking the winner on its own test data.

For contrast, a plain random split would report **0.967** for the chosen model. The gap is what near-duplicate titles do to a careless evaluation.

## Chosen model on unseen sites

- Confidence threshold **0.96**: the lowest that keeps precision at least 90%. At it, the model labels **60%** of productive/distracting titles with precision **0.90**; everything else keeps its app's default category. Being unsure and staying quiet is the intended behaviour.

```
              precision    recall  f1-score   support

  productive       0.76      0.88      0.82       262
     neutral       0.58      0.43      0.50       146
 distracting       0.78      0.78      0.78       206

    accuracy                           0.74       614
   macro avg       0.71      0.70      0.70       614
weighted avg       0.73      0.74      0.73       614
```

Confusion matrix (rows = true, columns = predicted):

| | productive | neutral | distracting |
|---|---|---|---|
| **productive** | 231 | 20 | 11 |
| **neutral** | 50 | 63 | 33 |
| **distracting** | 21 | 25 | 160 |

## Most confident mistakes (unseen sites)

| Confidence | Title | True | Predicted |
|---|---|---|---|
| 1.00 | JavaScript std::thread - W3Schools - Brave | distracting | productive |
| 1.00 | Machine Learning Unit 19 lecture notes.pdf - Microsoft​ Edge | distracting | productive |
| 1.00 | Discrete Maths Unit 8 lecture notes.pdf — Mozilla Firefox | distracting | productive |
| 1.00 | Watch Stranger Things / Netflix - Google Chrome | productive | distracting |
| 1.00 | Your Orders - Amazon.in — Mozilla Firefox | neutral | distracting |
| 1.00 | Your Orders - Amazon.in - Microsoft​ Edge | neutral | distracting |
| 1.00 | Your Orders - Amazon.in - Google Chrome | neutral | distracting |
| 1.00 | Your Orders - Amazon.in - Brave | neutral | distracting |
| 1.00 | Your Orders - Amazon.in | neutral | distracting |
| 1.00 | Priya (@Htet_29) • Instagram photos and videos — Mozilla Firefox | neutral | distracting |
| 1.00 | Binary Search Trees - Wikipedia - Microsoft​ Edge | productive | neutral |
| 1.00 | Bollywood - Wikipedia - Brave | neutral | productive |

Some mistakes are deliberate label noise: the demo data flips about 2% of labels, like a tired human labeller.

## What this means

- The model is reliable on sites it has examples of, and much weaker on sites it has never seen: a title classifier can only learn the vocabulary it is shown. More *different* sites in the training data helps far more than more titles from the same site.
- Only the window title is used. A title like "YouTube" on its own carries no information about the video.
- The label policy (what counts as productive) is a choice; the model learns whatever the labels say.
