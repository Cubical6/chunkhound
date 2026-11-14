<?php
namespace Acme\Notes\Model\Source;
class Color {
    public function getAllOptions() {
        return [
            ['value' => 'red', 'label' => 'Red'],
            ['value' => 'blue', 'label' => 'Blue'],
        ];
    }
}
