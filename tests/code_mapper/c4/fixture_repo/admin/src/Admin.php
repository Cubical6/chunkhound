<?php

declare(strict_types=1);

namespace Acme\Admin;

require_once __DIR__ . '/Base.php';

class Admin extends Base
{
    public function run(): string
    {
        return $this->name();
    }
}
