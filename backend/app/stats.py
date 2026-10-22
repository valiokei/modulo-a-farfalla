"""Event-derived statistics shared by the match tab and the coach dashboard.

Every value is computed from tagged events only; ``event_ids`` lets the UI
drill from a number back to the video.
"""
from .models import Event


def calculate_stats(events:list[Event]):
    groups:dict[str,list[Event]]={}
    for event in events:groups.setdefault(event.category.name,[]).append(event)
    ids=lambda *names:[e.id for name in names for e in groups.get(name,[])]
    count=lambda *names:len(ids(*names))
    successful=lambda names:[e.id for name in names for e in groups.get(name,[]) if e.metadata_.get("result") in ("successful","success","won") or e.metadata_.get("outcome") in ("successful","success")]
    saves=count("Save");conceded=count("Goal Conceded");faced=saves+conceded
    passes=ids("Pass","Forward Pass","Backward Pass","Lateral Pass","Progressive Pass","Through Ball","Line-breaking Pass","Key Pass","Long Pass","Switch of Play")
    pass_success=successful(["Pass","Forward Pass","Backward Pass","Lateral Pass","Progressive Pass","Through Ball","Line-breaking Pass","Key Pass","Long Pass","Switch of Play"])
    shots=ids("Shot","Shot on Target","Goal","Blocked Shot","Off Target","Post/Bar")
    on_target=ids("Shot on Target","Goal")+[e.id for e in groups.get("Shot",[]) if e.metadata_.get("outcome") in ("goal","saved")]
    possessions=groups.get("Possession",[]);duration=sum(max(0,(e.end or e.timestamp)-(e.start or e.timestamp)) for e in possessions)
    rows=[
        ("goalkeeping","shots faced",faced,ids("Save","Goal Conceded"),"manual"),("goalkeeping","saves",saves,ids("Save"),"manual"),("goalkeeping","goals conceded",conceded,ids("Goal Conceded"),"manual"),("goalkeeping","save %",round(saves/faced*100,1) if faced else 0,ids("Save","Goal Conceded"),"calculated"),
        ("overview","goals",count("Goal"),ids("Goal"),"manual"),("overview","shots",len(set(shots)),list(dict.fromkeys(shots)),"manual"),("overview","shots on target",len(set(on_target)),list(dict.fromkeys(on_target)),"calculated"),("overview","corners",count("Corner"),ids("Corner"),"manual"),("overview","free kicks",count("Free Kick"),ids("Free Kick"),"manual"),("overview","fouls",count("Foul"),ids("Foul"),"manual"),("overview","offsides",count("Offside"),ids("Offside"),"manual"),("overview","cards",count("Yellow Card","Red Card"),ids("Yellow Card","Red Card"),"manual"),
        ("passing","passes",len(passes),passes,"manual"),("passing","completed passes",len(pass_success),pass_success,"manual"),("passing","pass completion %",round(len(pass_success)/len(passes)*100,1) if passes else 0,passes,"calculated"),("passing","progressive passes",count("Progressive Pass"),ids("Progressive Pass"),"manual"),("passing","long passes",count("Long Pass"),ids("Long Pass"),"manual"),("passing","key passes",count("Key Pass"),ids("Key Pass"),"manual"),("passing","crosses",count("Cross"),ids("Cross"),"manual"),
        ("attacking","conversion rate",round(count("Goal")/len(set(shots))*100,1) if shots else 0,list(dict.fromkeys(shots)),"calculated"),("attacking","final-third entries",count("Final Third Entry"),ids("Final Third Entry"),"manual"),("attacking","penalty-area entries",count("Penalty Area Entry"),ids("Penalty Area Entry"),"manual"),
        ("defensive","tackles",count("Tackle"),ids("Tackle"),"manual"),("defensive","interceptions",count("Interception"),ids("Interception"),"manual"),("defensive","recoveries",count("Recovery"),ids("Recovery"),"manual"),("defensive","clearances",count("Clearance"),ids("Clearance"),"manual"),("defensive","blocks",count("Block"),ids("Block"),"manual"),("transition","counterpresses",count("Counterpress"),ids("Counterpress"),"manual"),("transition","turnovers",count("Ball Loss","Forced Turnover","Unforced Turnover"),ids("Ball Loss","Forced Turnover","Unforced Turnover"),"manual"),
        ("possession","possessions",len(possessions),[e.id for e in possessions],"manual"),("possession","average possession duration",round(duration/len(possessions),1) if possessions else 0,[e.id for e in possessions],"calculated"),
        ("goalkeeping","1v1",count("1v1"),ids("1v1"),"manual"),("goalkeeping","high balls",count("High Ball","Catch","Cross Claim","Punch"),ids("High Ball","Catch","Cross Claim","Punch"),"manual"),("goalkeeping","distributions",count("Distribution","Short Distribution","Long Distribution","Throw","Goal Kick"),ids("Distribution","Short Distribution","Long Distribution","Throw","Goal Kick"),"manual"),("goalkeeping","tagged errors",count("GK Error","Defensive Error","Error"),ids("GK Error","Defensive Error","Error"),"manual")]
    return [{"group":group,"name":name,"value":value,"event_ids":event_ids,"source":source} for group,name,value,event_ids,source in rows]
