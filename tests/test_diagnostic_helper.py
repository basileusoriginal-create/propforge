from test_spawn_placement import runtime


def native_stubs(g):
    # The generated script itself is executed by lupa; these are GTA responses.
    g._lua_test = True
    from lupa import LuaRuntime
    # Reuse the owning Lua VM through a callback compiled in the shared globals.
    g.load('''
        json={encode=function(r) last_report=r; return r.status end}
        function GetOffsetFromEntityInWorldCoords(obj,x,y,z)
            return {x=100+x,y=200+y,z=settings.surface+z}
        end
        function CreateCam() return 20 end
        function SetCamCoord(cam,x,y,z) camera_xyz={x,y,z} end
        function PointCamAtCoord() end
        function SetCamFov(cam,fov) last_fov=fov end
        function SetCamNearClip(cam,clip) near_clip=clip end
        function GetCamFov() return last_fov end
        function GetCamCoord() return {x=camera_xyz[1],y=camera_xyz[2],z=camera_xyz[3]} end
        function SetFocusPosAndVel() focus=true end
        function RenderScriptCams(enabled) rendering=enabled end
        function InvalidateIdleCam() end
        function ClearFocus() focus=false end
        function DestroyCam(cam) destroyed=cam end
        function IsModelInCdimage() return false end
    ''')()


def test_measure_reports_real_five_probe_gaps():
    g=runtime(); native_stubs(g)
    g.commands['pfmeasure']()
    assert g.last_report.status=='measured'
    assert g.last_report.within_2mm
    assert len(g.last_report.gap_mm)==5
    assert g.last_report.visual_and_walk_test=='pending'


def test_fixed_camera_uses_float_fov_and_restores_own_focus():
    g=runtime(); native_stubs(g)
    args=g.load("return {'feet'}")()
    g.commands['pfview'](0,args)
    assert g.rendering and g.focus
    assert g.last_fov==45.0
    assert g.near_clip==.01
    assert g.last_report.actual_selected_lod=='not_observable'
    assert abs(g.last_report.distance_m-g.last_report.requested_distance_m)<.0001
    g.commands['pfview'](0,g.load("return {'off'}")())
    assert not g.rendering and not g.focus and g.destroyed==20


def test_missing_gta_reference_is_reported():
    g=runtime(); native_stubs(g)
    g.commands['pfreference']()
    assert g.last_report.status=='failed'
    assert 'nicht verfuegbar' in g.last_report.error


def test_camera_measurement_waits_for_game_to_apply_position():
    g=runtime(); native_stubs(g)
    g.load('''
        camera_xyz={100,200,0}
        function SetCamCoord(cam,x,y,z) pending_xyz={x,y,z} end
        function Wait(ms) if pending_xyz then camera_xyz=pending_xyz; pending_xyz=nil end end
    ''')()
    g.commands['pfview'](0,g.load("return {'550'}")())
    assert g.last_report.status=='camera_ready'
    assert abs(g.last_report.distance_m-550)<.0001


def test_camera_line_does_not_pass_through_spawn_player():
    g=runtime(); native_stubs(g)
    g.commands['pfview'](0,g.load("return {'3'}")())
    # Prop center is (100,200), player stands two metres behind it.
    dx,dy=g.camera_xyz[1]-100,g.camera_xyz[2]-200
    import math
    distance_to_view_line=abs(dx*(-2.0))/math.hypot(dx,dy)
    assert distance_to_view_line > .5
