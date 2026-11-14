<?php
namespace App\Models;
class Missing extends BaseRecord {}
class Person extends BaseRecord {}
class ExplicitPerson extends BaseRecord { protected $table = 'people'; }
class AuditLog extends BaseRecord {}
