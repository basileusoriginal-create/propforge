"""Execute the actual generated Lua, with deterministic native responses."""
import pytest
from lupa import LuaRuntime

from propforge.packaging import render_spawn_helper


def runtime(bottom=0.0, **settings):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        commands, messages, rays, objects, deleted = {}, {}, {}, {}, {}
        settings = {loaded=true, hit=1, surface=38.28228759765625,
                    heading=0, status=2, legacy=1, create=10}
        ticks = 0
        function RegisterCommand(name,fn) commands[name]=fn end
        function AddEventHandler() end
        function GetHashKey(name) return name end
        function RequestModel() end
        function HasModelLoaded() return settings.loaded end
        function Wait(ms) ticks=ticks+math.max(ms,10) end
        function GetGameTimer() return ticks end
        function PlayerPedId() return 1 end
        function GetEntityCoords() return {x=100,y=200,z=39.28228759765625} end
        function GetEntityForwardVector() return {x=0,y=1,z=0} end
        function GetEntityHeading() return settings.heading end
        function RequestCollisionAtCoord() end
        function StartShapeTestLosProbe(x,y,z,tx,ty,tz,flags,ignore)
            rays[#rays+1]={x=x,y=y,z=z,to_z=tz,flags=flags,ignore=ignore}
            return #rays
        end
        function GetShapeTestResult(handle)
            local height=settings.surface
            if settings.uneven and handle==4 then height=height+.1 end
            return settings.status,settings.hit,{z=height}
        end
        function CreateObjectNoOffset(hash,x,y,z)
            objects[#objects+1]={x=x,y=y,z=z,hash=hash,exact=true}
            return settings.create
        end
        function CreateObject(hash,x,y,z)
            objects[#objects+1]={x=x,y=y,z=z,hash=hash,exact=false}
            return settings.create
        end
        function PlaceObjectOnGroundProperly() return settings.legacy end
        function SetEntityHeading(obj,h) end
        function FreezeEntityPosition(obj) frozen=obj end
        function SetModelAsNoLongerNeeded() released=true end
        function DoesEntityExist() return true end
        function DeleteEntity(obj) deleted[#deleted+1]=obj end
        function print(text) messages[#messages+1]=text end
    ''')
    for key, value in settings.items(): lua.globals().settings[key] = value
    bounds = {} if bottom is None else {"pf_desk": {"min": [-.8,-.4,bottom], "max": [.8,.4,bottom+.75]}}
    lua.execute(render_spawn_helper(["pf_desk"], bounds))
    lua.globals().commands["pfspawn"](0, lua.table_from(["pf_desk"]))
    return lua.globals()


@pytest.mark.parametrize("bottom", [0.0, -.375, 2.0])
@pytest.mark.parametrize("hit", [True, 1])
def test_visible_bottom_is_on_roof_for_preserved_origins(bottom, hit):
    g = runtime(bottom, hit=hit)
    assert g.objects[1].exact
    assert g.objects[1].z + bottom == pytest.approx(g.settings.surface)
    assert len(g.rays) == 5
    assert g.frozen == 10
    assert g.released
    g.commands["pfdelete"](0, g.objects)
    assert len(g.deleted) == 1


@pytest.mark.parametrize("settings", [dict(hit=False), dict(hit=0), dict(status=0),
                                     dict(status=1), dict(uneven=True), dict(loaded=False)])
def test_no_successful_spawn_on_failed_or_uneven_surface(settings):
    g = runtime(**settings)
    assert len(g.objects) == 0
    assert g.frozen is None
    assert any("abgebrochen" in g.messages[i] or "konnte nicht geladen" in g.messages[i]
               for i in range(1,len(g.messages)+1))


def test_rotates_footprint_with_heading():
    g = runtime(heading=90)
    assert g.rays[1].x == pytest.approx(100.4)
    assert g.rays[1].y == pytest.approx(201.2)


def test_legacy_metadata_absence_is_reported():
    g = runtime(bottom=None)
    assert not g.objects[1].exact
    assert len(g.rays) == 0
    assert "Bodenbezug ungesichert" in g.messages[1]


@pytest.mark.parametrize("result", [False, 0])
def test_failed_legacy_placement_is_deleted(result):
    g = runtime(bottom=None, legacy=result)
    assert len(g.deleted) == 1
    assert g.frozen is None


def test_entity_creation_failure_is_not_frozen():
    g = runtime(create=0)
    assert g.frozen is None
    assert g.released
