"""Domestic DEMO inventory. Airport directory is not an operating-route promise."""
import json
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from flask import jsonify, request

DIRECTORY=json.loads((Path(__file__).parent/'static/airports.json').read_text(encoding='utf8'))
AIRPORTS={a['code'] for a in DIRECTORY}
AVAILABLE={a['code'] for a in DIRECTORY if a['demo_available']}
CABINS={'economy':100,'premium':160,'business':280,'first':450}
AIRLINES=[('Thai AirAsia','FD',0),('Nok Air','DD',180),('Thai Lion Air','SL',320),('Thai Vietjet','VZ',100),('Thai Airways','TG',1200)]

def party(data):
    adults=data.get('adults',data.get('count',1));children=data.get('children',0);infants=data.get('infants',0)
    if any(type(v) is not int for v in (adults,children,infants)) or not 1<=adults<=6 or not 0<=children<=5 or not 0<=infants<=adults or adults+children+infants>9 or data.get('count')!=adults+children+infants:
        raise ValueError('ผู้ใหญ่ 1–6 คน รวมไม่เกิน 9 คน และทารกไม่เกินจำนวนผู้ใหญ่')
    return adults,children,infants

def catalogue(origin,destination,travel_date,cabin='economy',connections=True):
    if origin not in AIRPORTS or destination not in AIRPORTS or origin==destination or cabin not in CABINS:
        raise ValueError('เส้นทางหรือชั้นโดยสารไม่ถูกต้อง')
    d=date.fromisoformat(travel_date)
    if origin not in AVAILABLE or destination not in AVAILABLE or cabin=='first':return []
    seed=sum((i+1)*ord(c) for i,c in enumerate(origin+destination))
    base=590+seed%8*95+(d.toordinal()%7)*40
    duration=55+seed%7*10
    inventory=[]
    for ai,(air,prefix,extra) in enumerate(AIRLINES):
        if cabin!='economy' and prefix!='TG':continue
        for slot in range(6):
            minute=330+slot*185+ai*13+(d.toordinal()%3)*5
            end=minute+duration
            price=round((base+extra+[0,450,850,250,1300,650][slot])*CABINS[cabin]/100)
            code=f'{prefix}{100+ai*100+slot}{origin}{destination}{d:%m%d}'
            inventory.append(dict(air=air,code=code,price=price,start=f'{minute//60:02}:{minute%60:02}',end=f'{end//60%24:02}:{end%60:02}',duration=duration,arrival_day=end//1440,**{'from':origin,'to':destination,'date':d.isoformat(),'cabin':cabin,'demo':True}))
    cutoff=datetime.now(timezone(timedelta(hours=7)))+timedelta(hours=2)
    inventory=[f for f in inventory if datetime.fromisoformat(f['date']+'T'+f['start']).replace(tzinfo=cutoff.tzinfo)>=cutoff]
    if connections and 'BKK' not in (origin,destination):
        outbound=catalogue(origin,'BKK',travel_date,cabin,False)
        onward=catalogue('BKK',destination,travel_date,cabin,False)
        combinations=[]
        for first in outbound:
            arrival=first['arrival_day']*1440+int(first['end'][:2])*60+int(first['end'][3:])
            for second in onward:
                start=int(second['start'][:2])*60+int(second['start'][3:]);wait=start-arrival
                if first['air']==second['air'] and 90<=wait<=240:
                    f=dict(first);f.update(code='CON-'+first['code']+'-'+second['code'],end=second['end'],to=destination,price=first['price']+second['price'],duration=first['duration']+wait+second['duration'],arrival_day=second['arrival_day'],stops=1,via='BKK',layover_minutes=wait,segments=[first,second]);combinations.append(f)
        inventory.extend(sorted(combinations,key=lambda f:f['price'])[:10])
    return sorted(inventory,key=lambda f:(f['price'],f['start']))

def fare_total(data):
    adults,children,infants=party(data)
    return sum(f['price']*adults+percentage(f['price'],75)*children+percentage(f['price'],10)*infants for f in data['flights'])

def percentage(value,rate):
    """Whole-baht half-up rounding, identical to positive JS Math.round."""
    return (value*rate+50)//100

def promotion(data,today):
    code=data.get('promo_code','')
    if not code:return dict(code='',discount=0)
    if code!='ISAN10' or data['to'] not in {'KKC','UTH'} or date.fromisoformat(data['depart']).strftime('%Y-%m')!=today.strftime('%Y-%m'):
        raise ValueError('ISAN10 ใช้เดินทางไปขอนแก่นหรืออุดรธานีภายในเดือนปัจจุบันเท่านั้น')
    if data.get('use_member_benefit'):raise ValueError('โปรโมชันใช้ร่วมกับส่วนลดสมาชิกไม่ได้')
    return dict(code=code,discount=percentage(fare_total(data),10),month=today.strftime('%Y-%m'))

def configure_travel(app):
    @app.get('/api/flights')
    def flights():
        try:
            travel=request.args.get('date','')
            if date.fromisoformat(travel)<datetime.now(timezone(timedelta(hours=7))).date():raise ValueError('วันที่เดินทางต้องไม่อยู่ในอดีต')
            return jsonify(flights=catalogue(request.args.get('from'),request.args.get('to'),travel,request.args.get('cabin','economy')),demo=True)
        except (ValueError,TypeError):return jsonify(error='กรุณาตรวจสอบเส้นทาง วันที่ และชั้นโดยสาร'),400
