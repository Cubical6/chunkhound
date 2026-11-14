<?php
namespace Acme\Notes\Setup\Patch\Data;
use Magento\Catalog\Model\Product;
use Magento\Eav\Setup\EavSetupFactory;
use Acme\Notes\Model\Source\Color;
use Magento\Catalog\Model\Product\Attribute\Source\Status;
class AddAttributes {
    public function __construct(private EavSetupFactory $eavSetupFactory) {}
    public function apply() {
        $setup = $this->eavSetupFactory->create();
        $setup->addAttribute(Product::ENTITY, 'external_code', [
            'type' => 'varchar', 'required' => true, 'unique' => true,
        ]);
        $setup->addAttribute('catalog_product', 'color', [
            'type' => 'int', 'source' => Color::class,
        ]);
        $setup->addAttribute(Product::ENTITY, 'status', [
            'type' => 'int', 'required' => false, 'source' => Status::class,
        ]);
        $setup->addAttribute(Product::ENTITY, $dynamicCode, ['type' => 'text']);
    }
}
