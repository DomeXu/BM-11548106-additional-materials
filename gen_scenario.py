import os, sys, subprocess, xml.etree.ElementTree as ET
def bin_path(name): 
    sh=os.environ.get("SUMO_HOME"); 
    return os.path.join(sh,"bin",name) if sh else name
def main():
    here=os.path.abspath(os.path.dirname(__file__))
    net= os.path.join(here,"ev_map.net.xml")
    trips=os.path.join(here,"trips_600.trips")
    rou_base=os.path.join(here,"ev_routes_base_600.rou.xml")
    rou_ev=  os.path.join(here,"ev_routes_ev_600.rou.xml")
    addfile= os.path.join(here,"additional_stop.add.xml")

    subprocess.check_call([bin_path("netgenerate"),"--grid","--grid.number","3","--grid.length","200",
                           "--default.lanenumber","1","--default.speed","13.89","--output-file",net])
    
    randomTrips=os.path.join(os.environ["SUMO_HOME"],"tools","randomTrips.py")
    subprocess.check_call([sys.executable,randomTrips,"-n",net,"-e","3600","-p","6.0","-o",trips,"--seed","42","--min-distance","50"])
    
    subprocess.check_call([bin_path("duarouter"),"-n",net,"-t",trips,"-o",rou_base])
   
    tree=ET.parse(rou_base); root=tree.getroot()
    vtype=ET.Element("vType",{"id":"EV","vClass":"passenger","maxSpeed":"13.89","accel":"2.0","decel":"4.5"})
    for k,v in [("device.battery.probability","1"),("device.battery.capacity","50"),
                ("device.battery.vehicleMass","1500"),("device.battery.powerMaximum","80"),
                ("device.battery.recuperationEfficiency","0.6"),("device.battery.device","true"),
                ("device.battery.initialSoc","0.25"),("device.battery.minimumSoc","0.10")]:
        ET.SubElement(vtype,"param",{"key":k,"value":v})
    root.insert(0,vtype)
    for veh in root.findall("vehicle"): veh.set("type","EV")
    tree.write(rou_ev,encoding="utf-8",xml_declaration=True)
    
    sys.path.insert(0,os.path.join(os.environ["SUMO_HOME"],"tools"))
    from sumolib.net import readNet
    netobj=readNet(net); nodes=list(netobj.getNodes())
    xs=[n.getCoord()[0] for n in nodes]; ys=[n.getCoord()[1] for n in nodes]
    cx=0.5*(min(xs)+max(xs)); cy=0.5*(min(ys)+max(ys))
    center=min(nodes,key=lambda n:(n.getCoord()[0]-cx)**2+(n.getCoord()[1]-cy)**2)
    lanes=[]; 
    for e in center.getIncoming():
        for ln in e.getLanes(): lanes.append(ln)
    lanes=sorted(lanes,key=lambda L:-L.getLength())[:4]
    add=ET.Element("additional")
    for i,ln in enumerate(lanes):
        L=ln.getLength(); s=max(10.0,min(20.0,0.2*L)); e=min(L-5.0,max(60.0,0.4*L))
        ET.SubElement(add,"chargingStation",{"id":f"CS_{i}","lane":ln.getID(),
                      "startPos":f"{s:.1f}","endPos":f"{e:.1f}","power":"50",
                      "efficiency":"0.9","chargeInTransit":"false"})
    ET.ElementTree(add).write(addfile,encoding="utf-8",xml_declaration=True)
    print("OK:", rou_ev, addfile)
if __name__=="__main__": main()
