"""Statistical helpers only. Report and Markdown generators are external."""
import numpy as np

def interval(group_values,seed=42,draws=2000):
    values=np.array(list(group_values),dtype=float)
    if len(values)<2:return [None,None]
    rng=np.random.default_rng(seed)
    bootstrap=values[rng.integers(0,len(values),size=(draws,len(values)))].mean(axis=1)
    return [float(x) for x in np.quantile(bootstrap,[.025,.975])]

def holm(ps):
    ordered=sorted(range(len(ps)),key=lambda i:ps[i]);adjusted=[1.]*len(ps);last=0
    for rank,i in enumerate(ordered):
        last=max(last,min(1.,ps[i]*(len(ps)-rank)));adjusted[i]=last
    return adjusted
