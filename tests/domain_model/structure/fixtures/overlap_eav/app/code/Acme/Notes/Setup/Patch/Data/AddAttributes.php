<?php
namespace Acme\Notes\Setup\Patch\Data;
use Magento\Eav\Setup\EavSetup;
use Acme\Notes\Model\Source\Color;
class AddAttributes {
    public function apply(EavSetup $setup) {
        $setup->addAttribute('catalog_product', 'external_code', [
            'type' => 'varchar', 'required' => true, 'unique' => true,
        ]);
        $setup->addAttribute('catalog_product', 'color', [
            'type' => 'int', 'source' => Color::class,
        ]);
    }
}
