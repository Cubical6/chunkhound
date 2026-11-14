<?php
namespace App\Http\Controllers;
use App\Models\TeamUser;
use App\Http\Requests\StoreTeamMemberRequest;
use Illuminate\Support\Facades\Validator;
class TeamMemberController extends BaseController {
    public function index() {}
    public function store(StoreTeamMemberRequest $request, TeamUser $member) {
        $request->validate(['nickname' => 'nullable|string']);
        Validator::make($request->all(), ['age' => ['integer', 'min:18']]);
    }
    public function show() {}
    public function update() {}
    public function destroy() {}
    public function create() {}
    public function edit() {}
    public function __invoke() {}
}
