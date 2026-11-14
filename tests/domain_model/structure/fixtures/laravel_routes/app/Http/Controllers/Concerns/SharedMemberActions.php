<?php
namespace App\Http\Controllers\Concerns;
use App\Models\TeamUser;
use App\Http\Requests\StoreTeamMemberRequest;
trait SharedMemberActions {
    public function fromTrait(StoreTeamMemberRequest $request, TeamUser $member) {}
}
