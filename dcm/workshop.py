from .database import get_setting,tax_rate
from .economics import best_unit,lot_purchase_plan
from .engine import build_engine

def make_workshop_context(con,use_inventory=True):
    calc,_,recipes=build_engine(con)
    item_rows={r["id"]:dict(r) for r in con.execute("SELECT id,name,category,subtype,image FROM items")}
    price_rows={r["item_id"]:r for r in con.execute("SELECT * FROM prices")}
    inventory=({r["item_id"]:int(r["quantity"] or 0) for r in con.execute("SELECT item_id,quantity FROM inventory")} if use_inventory else {})
    return {"calc":calc,"recipes":recipes,"item_rows":item_rows,"price_rows":price_rows,"inventory":inventory}

def build_workshop_plan(con,selections,use_inventory=True,context=None):
    context=context or make_workshop_context(con,use_inventory)
    calc=context["calc"];recipes=context["recipes"];item_rows=context["item_rows"];price_rows=context["price_rows"]
    available=dict(context["inventory"]) if use_inventory else {}
    purchases={};crafts={};stock_used={};missing={};visiting=set()
    def add(target,item_id,qty): target[item_id]=target.get(item_id,0)+int(qty)
    def fulfill(item_id,qty,allow_stock=True):
        qty=max(int(qty or 0),0)
        if not qty:return
        use=min(available.get(item_id,0),qty) if allow_stock else 0
        if use: available[item_id]-=use;add(stock_used,item_id,use);qty-=use
        if not qty:return
        state=calc(item_id);recipe=recipes.get(item_id)
        if item_id not in visiting and recipe and state.get('mode')=='fabriquer':
            add(crafts,item_id,qty);visiting.add(item_id)
            for ing,amount in recipe:fulfill(ing,qty*amount)
            visiting.remove(item_id);return
        row=price_rows.get(item_id);old=purchases.get(item_id);total=qty+(old['quantity'] if old else 0)
        plan=lot_purchase_plan(total,row['p1'] if row else None,row['p10'] if row else None,row['p100'] if row else None)
        if plan.get('cost') is None:add(missing,item_id,qty)
        else:purchases[item_id]=plan
    for entry in selections or []: fulfill(int(entry.get('item_id') or 0),int(entry.get('quantity') or 0),False)
    def decorate(mapping):
        return sorted([{**item_rows.get(i,{'name':f'#{i}'}),'item_id':i,'quantity':q} for i,q in mapping.items()],key=lambda x:x.get('name',''))
    buy=[];total=0.0
    for i,plan in purchases.items():
        total+=float(plan.get('cost') or 0);buy.append({**item_rows.get(i,{'name':f'#{i}'}),'item_id':i,**plan})
    buy.sort(key=lambda x:x.get('name',''))
    rate=tax_rate(con) if get_setting(con,'sale_tax_enabled','1')!='0' else 0.0
    gross_sale=0.0;total_output_quantity=0;missing_sales={}
    for entry in selections or []:
        output_id=int(entry.get('item_id') or 0);output_qty=max(int(entry.get('quantity') or 0),0)
        if not output_id or not output_qty:continue
        total_output_quantity+=output_qty;sale_unit=best_unit(price_rows.get(output_id))[0]
        if sale_unit is None:add(missing_sales,output_id,output_qty)
        else:gross_sale+=sale_unit*output_qty
    sale_tax=gross_sale*rate;net_sale=gross_sale-sale_tax
    profit=net_sale-total if not missing and not missing_sales else None
    roi=profit/total*100 if profit is not None and total>0 else None
    average_profit=profit/total_output_quantity if profit is not None and total_output_quantity else None
    complete=not bool(missing) and not bool(missing_sales)
    return {'purchases':buy,'crafts':decorate(crafts),'stock_used':decorate(stock_used),'missing':decorate(missing),
            'missing_sales':decorate(missing_sales),'total_cost':total,'gross_sale':gross_sale,'sale_tax':sale_tax,
            'net_sale':net_sale,'profit':profit,'roi':roi,'average_profit':average_profit,
            'total_output_quantity':total_output_quantity,'complete':complete,'tax_rate':rate}

def strict_budget_plan(con,item_id,budget,estimated_unit_cost,context):
    budget=max(float(budget or 0),0.0)
    if budget<=0 or not estimated_unit_cost or estimated_unit_cost<=0:return 0,0.0
    high=max(int(budget//estimated_unit_cost),0)
    if high<=0:return 0,0.0
    cost_cache={}
    def real_cost(quantity):
        if quantity not in cost_cache:
            plan=build_workshop_plan(con,[{"item_id":item_id,"quantity":quantity}],use_inventory=False,context=context)
            cost_cache[quantity]=float(plan["total_cost"]) if plan.get("complete") else None
        return cost_cache[quantity]
    low=0;best_cost=0.0
    while low<high:
        mid=(low+high+1)//2;cost=real_cost(mid)
        if cost is not None and cost<=budget:low=mid;best_cost=cost
        else:high=mid-1
    if low and not best_cost:best_cost=real_cost(low) or 0.0
    return low,best_cost
