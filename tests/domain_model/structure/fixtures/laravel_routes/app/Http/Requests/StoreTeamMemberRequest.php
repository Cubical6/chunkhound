<?php
namespace App\Http\Requests;
use Illuminate\Foundation\Http\FormRequest;
class StoreTeamMemberRequest extends FormRequest {
    public function rules() {
        return [
            'email' => 'required|email',
            'invite_code' => ['required', 'string'],
            'dynamic_rule' => $rule,
        ];
    }
}
