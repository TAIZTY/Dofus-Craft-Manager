def lot_purchase_plan(quantity, p1, p10, p100):
    quantity = max(int(quantity or 0), 0)
    prices = {1: float(p1) if p1 and p1 > 0 else None,
              10: float(p10) if p10 and p10 > 0 else None,
              100: float(p100) if p100 and p100 > 0 else None}
    empty = {"quantity": quantity, "cost": None, "units": 0, "overbuy": 0,
             "lots": {"x1": 0, "x10": 0, "x100": 0}}
    if quantity <= 0:
        return {**empty, "cost": 0.0, "label": "aucun achat", "options": []}
    options = []
    for size, key in ((1,"x1"),(10,"x10"),(100,"x100")):
        price = prices[size]
        if price is not None:
            count = (quantity + size - 1)//size
            units = count*size
            options.append({"type":key,"lots":count,"units":units,
                            "overbuy":units-quantity,"cost":count*price})
    best = None
    max100 = (quantity+99)//100 + (1 if prices[100] is not None else 0)
    n100_values = range(max100+1) if prices[100] is not None else (0,)
    for n100 in n100_values:
        remaining = max(quantity-n100*100, 0)
        n10_values = {0, remaining//10, (remaining+9)//10} if prices[10] is not None else {0}
        for n10 in n10_values:
            units = n100*100+n10*10
            n1 = max(quantity-units,0)
            if n1 and prices[1] is None: continue
            total_units = units+n1
            if total_units < quantity: continue
            cost = n100*(prices[100] or 0)+n10*(prices[10] or 0)+n1*(prices[1] or 0)
            candidate=(cost,total_units-quantity,n100+n10+n1,n1,n10,n100)
            if best is None or candidate < best[0]:
                best=(candidate,{"quantity":quantity,"cost":cost,"units":total_units,
                                 "overbuy":total_units-quantity,
                                 "lots":{"x1":n1,"x10":n10,"x100":n100}})
    result = best[1] if best else empty
    parts=[]
    for key in ("x100","x10","x1"):
        count=result["lots"].get(key,0)
        if count: parts.append(f'{count} lot{"s" if count>1 else ""} {key}')
    result["label"]=" + ".join(parts) if parts else "prix manquant"
    result["options"]=options
    return result

def best_unit(row):
    values=[]
    if row and row["p1"] not in (None,0): values.append((float(row["p1"]),"x1"))
    if row and row["p10"] not in (None,0): values.append((float(row["p10"])/10,"x10"))
    if row and row["p100"] not in (None,0): values.append((float(row["p100"])/100,"x100"))
    return min(values) if values else (None,None)
