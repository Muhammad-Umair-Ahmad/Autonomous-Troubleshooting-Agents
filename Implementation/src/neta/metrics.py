"""Set-valued deterministic evaluator. Empty-set conventions are explicit."""
from .contracts import Fault

def score(predicted, actual):
    p={Fault.model_validate(x).identity() for x in predicted}
    a={Fault.model_validate(x).identity() for x in actual}
    tp=len(p&a); fp=len(p-a); fn=len(a-p)
    ranked=list(dict.fromkeys(Fault.model_validate(x).identity() for x in predicted))
    precision=tp/len(p) if p else float(not a)
    recall=tp/len(a) if a else float(not p)
    return {'precision':precision,'recall':recall,'f1':2*precision*recall/(precision+recall) if precision+recall else 0.,
            'exact_match':int(p==a),'tp':tp,'fp':fp,'fn':fn,'fault_count':len(a),
            'healthy_correct':int(not p) if not a else None,'false_alarm':int(bool(p)) if not a else None,
            'recall_at_3':len(set(ranked[:3])&a)/len(a) if a else None,
            'recall_at_5':len(set(ranked[:5])&a)/len(a) if a else None,
            'top1':int(bool(a) and bool(predicted) and Fault.model_validate(predicted[0]).identity() in a) if a else None,
            'reciprocal_rank':next((1/(i+1) for i,f in enumerate(predicted) if Fault.model_validate(f).identity() in a),0) if len(a)==1 else None}
